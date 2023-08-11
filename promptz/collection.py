import json
import uuid
from datetime import datetime
from abc import abstractmethod
from typing import Any, Dict
import pandas as pd
from pydantic import BaseModel 
from IPython.display import display, HTML
import chromadb


class Query(BaseModel):
    query: str
    where: Dict[str, Any] = None
    collection: str = None

    def __init__(self, query, where=None, collection=None, **kwargs):
        super().__init__(query=query, where=where, collection=collection, **kwargs)


class VectorDB:

    @abstractmethod
    def query(self, texts, where=None, **kwargs):
        '''
        Query embeddings using a list of texts and optional where clause.
        '''

    @abstractmethod
    def get_or_create_collection(self, name, **kwargs):
        '''
        Return a collection or create a new one if it doesn't exist.
        '''


class ChromaVectorDB(VectorDB):

    def __init__(self, endpoint=None, api_key=None, **kwargs):
        self.client = chromadb.Client()

    def query(self, texts, where=None, **kwargs):
        return self.client.query(texts, where=where, **kwargs)
    
    def get_or_create_collection(self, name, **kwargs):
        return self.client.get_or_create_collection(name, **kwargs)


class Entity(BaseModel):
    id: str = None

    class Config:
        extra = 'allow'
        arbitrary_types_allowed = True
    
    def __init__(self, **data):
        super().__init__(**data)
    
    def __repr__(self):
        return self.json()
    
    def display(self):
        # Check if we're in an IPython environment
        try:
            get_ipython
        except NameError:
            # If we're not in an IPython environment, fall back to json
            return self.json()

        # Convert the dictionary to a HTML table
        html = '<table>'
        for field, value in self.dict().items():
            html += f'<tr><td>{field}</td><td>{value}</td></tr>'
        html += '</table>'

        # Display the table
        display(HTML(html))
        return self.json()


class EntitySeries(pd.Series):

    @property
    def _constructor(self):
        return EntitySeries

    @property
    def _constructor_expanddim(self):
        return Collection
    
    @property
    def object(self):
        d = self.to_dict()
        return Entity(**d)


class Collection(pd.DataFrame):
    _metadata = ['collection']

    @property
    def _constructor(self, *args, **kwargs):
        return Collection
    
    @property
    def _constructor_sliced(self):
        return EntitySeries
    
    @classmethod
    def load(cls, collection):
        records = collection.get(where={'item': 1})
        docs = [
            {'id': id, **json.loads(r)} 
            for id, r in zip(records['ids'], records['documents'])
        ]
        c = Collection(docs)
        c.collection = collection
        return c
    
    def embedding_query(self, *texts, ids=None, where=None, threshold=0.69, **kwargs):
        texts = [t for t in texts if t is not None]
        
        scores = {}
        if len(texts) == 0:
            results = self.collection.get(ids=ids, where=where, **kwargs)
            for id, m in zip(results['ids'], results['metadatas']):
                if m.get('item') != 1:
                    id = m.get('item_id')
                if id not in scores:
                    scores[id] = 1
                else:
                    scores[id] += 1
        else:
            results = self.collection.query(query_texts=texts, ids=ids, where=where, **kwargs)
            for i in range(len(results['ids'])):
                for id, d, m in zip(results['ids'][i], results['distances'][i], results['metadatas'][i]):
                    if m.get('item') != 1:
                        id = m.get('item_id')
                    if id not in scores:
                        scores[id] = 1 - d
                    else:
                        scores[id] += 1 - d
        
        try:
            df = self.copy()
            df['score'] = df['id'].map(scores)
            df = df[df['score'].notna()]
            df = df.sort_values('score', ascending=False)
            df = df.drop(columns=['score'])
            return df
        except KeyError as e:
            return None
    
    def __call__(self, *texts, where=None, **kwargs) -> Any:
        return self.embedding_query(*texts, where=where, **kwargs)
    
    @property
    def name(self):
        return self.collection.name
    
    @property
    def objects(self):
        return [r.object for _, r in self.iterrows()]
    
    @property
    def first(self):
        if len(self.objects) == 0:
            return None
        else:
            return self.objects[0]
    
    def embed(self, *items, **kwargs):
        records = []
        new_items = []
        unique_columns = {}
        for item in items:
            new_item = False
            try:
                id = item.id
            except AttributeError:
                id = str(uuid.uuid4())
                new_item = True

            now = datetime.now().isoformat()

            for name, field in item.__fields__.items():
                try:
                    if field.field_info.default[0].extra.get('unique'):
                        unique_columns[name] = True
                except Exception as e:
                    pass

                f = { name: getattr(item, name) }
                # TODO: Handle nested fields
                field_record = {
                    'id': f'{id}_{name}',
                    'document': json.dumps(f),
                    'metadata': {
                        'field': name,
                        'collection': self.name,
                        'item': 0,
                        'item_id': id,
                        'created_at': now,
                    },
                }
                records.append(field_record)
                if new_item: 
                    new_items.append(field_record)

            type_ = getattr(item, 'type', item.__class__.__name__.lower())
            doc_record = {
                'id': id,
                'document': item.json(),
                'metadata': {
                    'collection': self.name,
                    'type': type_,
                    'item': 1,
                    'created_at': now,
                },
            }

            records.append(doc_record)
            if new_item:
                new_items.append(doc_record)
            
        self.collection.upsert(
            ids=[r['id'] for r in records],
            documents=[r['document'] for r in records],
            metadatas=[r['metadata'] for r in records],
        )

        docs = [{'id': r['id'], **json.loads(r['document'])} for r in new_items]
        df = pd.concat([self, Collection(docs)], ignore_index=True)
        self.drop(self.index, inplace=True)
        for column in df.columns:
            self[column] = df[column]
        return self