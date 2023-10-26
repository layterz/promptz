import uuid
import json
from enum import Enum
from datetime import datetime
from abc import abstractmethod
from typing import *
from loguru import logger
import pandas as pd
from pydantic import BaseModel, Field, ConfigDict
from pydantic_core._pydantic_core import PydanticUndefinedType
import chromadb


from .utils import create_model_from_schema, create_entity_from_schema, _is_list_type, PYTYPE_TO_JSONTYPE, get_args


class Entity(BaseModel):
    id: str = None
    type: str = None
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    def __init__(self, id=None, **data):
        if 'type' not in data:
            data['type'] = self.__class__.__name__.lower()
        
        super().__init__(**{'id': id or str(uuid.uuid4()), **data})
    
    @classmethod
    def load(cls, id=None, **kwargs):
        for name, field in cls.__annotations__.items():
            if isinstance(field, type) and issubclass(field, Entity):
                def loader():
                    # Lazy-loading logic here
                    logger.info(f'Loading {name}')
                    return None
                
                setattr(cls, name, property(loader))
        return cls(id=id, **kwargs)
    
    @classmethod
    def generate_schema_for_field(cls, name, field_type: Any, field: Field):
        return_list = False
        definitions = {}

        if _is_list_type(field_type):
            field_type = get_args(field_type)[0]
            return_list = True
        
        # Handle enums
        if isinstance(field_type, type) and issubclass(field_type, Enum):
            schema = {
                "type": "string",
                "enum": [e.name.lower() for e in field_type],
            }

        # Handle basic types
        elif isinstance(field_type, type) and issubclass(field_type, (int, float, str, bool)):
            type_ = PYTYPE_TO_JSONTYPE[field_type]
            schema = {"type": type_}

        # Handle Pydantic model types (reference schema)
        elif isinstance(field_type, type) and issubclass(field_type, Entity):
            schema = {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "type": {"type": "string"},
                },
            }
        
        # Handle default case by getting the cls field and calling schema
        else:
            if isinstance(field_type, list):
                field_type = field_type[0]
            if field_type.__name__ not in definitions:
                definitions[field_type.__name__] = {
                    "type": "object",
                    "properties": field.default.schema() if field.default is not None else {}
                }
            schema = {"$ref": f"#/$defs/{field_type.__name__}"} 

        if return_list:
            schema = {
                "type": "array",
                "items": schema,
            }
        
        # TODO: need to test/fix this
        info = None
        if info is not None:
            if info.description:
                schema['description'] = info.description
            if info.ge:
                schema['ge'] = info.ge
            if info.gt:
                schema['gt'] = info.gt
            if info.le:
                schema['le'] = info.le
            if info.lt:
                schema['lt'] = info.lt
            if info.min_length:
                schema['min_length'] = info.min_length
            if info.max_length:
                schema['max_length'] = info.max_length
            
            extra = info.extra
            if extra is not None:
                if 'generate' in extra:
                    schema['generate'] = extra['generate']

        if field.default:
            schema['default'] = field.default
        return schema, definitions, []
    
    @classmethod
    def schema(cls, by_alias: bool = True, **kwargs):
        properties = {}
        required = []
        definitions = {}

        for field_name, field in cls.model_fields.items():
            try:
                type_ = cls.__annotations__.get(field_name, field.annotation)
                field_schema, defs, reqs = cls.generate_schema_for_field(field_name, type_, field)
                properties[field_name] = field_schema
                definitions = {**definitions, **defs}
            except Exception as e:
                logger.error('schema field failed', field_name, e, field)
                continue
            
            if field.is_required():
                required.append(field_name)
            required += reqs

        # Construct the base schema
        base_schema = {
            "title": cls.__name__,
            "type": "object",
            "properties": properties,
            "$defs": definitions,  # Include definitions for references
            "required": required,
        }

        return base_schema
    
    def display(self):
        return self.model_dump_json()
    

class Query(BaseModel):
    type: str = 'query'
    query: str = None
    where: Dict[str, (int|str|bool)] = None
    collection: str = None

    def __init__(self, query=None, where=None, collection=None, **kwargs):
        super().__init__(query=query, where=where, collection=collection, **kwargs)


class Subscription(Entity):
    type: str = 'subscription'
    query: Query = None

    def __init__(self, query=None, **kwargs):
        super().__init__(query=query, **kwargs)


class VectorDB:
    name: str

    @abstractmethod
    def get(self, ids=None, where=None, **kwargs):
        '''
        Get embeddings by ids or where clause.
        '''

    @abstractmethod
    def query(self, texts, where=None, ids=None, **kwargs):
        '''
        Query embeddings using a list of texts and optional where clause.
        '''

    @abstractmethod
    def get_collection(self, name, **kwargs):
        '''
        Return a collection if it exists.
        '''

    @abstractmethod
    def get_or_create_collection(self, name, **kwargs):
        '''
        Return a collection or create a new one if it doesn't exist.
        '''

    @abstractmethod
    def delete_collection(self, name, **kwargs):
        '''
        Return a collection or create a new one if it doesn't exist.
        '''
    
    @abstractmethod
    def collections():
        '''
        Return a list of collections.
        '''
    
    @abstractmethod
    def upsert(self, ids, documents, metadatas, **kwargs):
        '''
        Upsert embeddings.
        '''


class ChromaVectorDB(VectorDB):

    def __init__(self, endpoint=None, api_key=None, path=None, **kwargs):
        self.client = chromadb.PersistentClient(path=f'{path}/.px/db' if path else "./.px/db")

    def query(self, texts, where=None, ids=None, **kwargs):
        return self.client.query(texts, where=where, **kwargs)
    
    def get_or_create_collection(self, name, **kwargs):
        return self.client.get_or_create_collection(name, **kwargs)
    
    def create_collection(self, name, **kwargs):
        return self.client.create_collection(name, **kwargs)
    
    def get_collection(self, name, **kwargs):
        try:
            return self.client.get_collection(name, **kwargs)
        except ValueError:
            return None
    
    def delete_collection(self, name, **kwargs):
        return self.client.delete_collection(name, **kwargs)
    
    def collections(self):
        return self.client.list_collections()
    
    def upsert(self, ids, documents, metadatas, **kwargs):
        return self.client.upsert(ids, documents, metadatas, **kwargs)
    
    def get(self, ids=None, where=None, **kwargs):
        return self.client.get(ids=ids, where=where, **kwargs)


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
    _metadata = ['db', 'schema']

    @property
    def _constructor(self, *args, **kwargs):
        return Collection
    
    @property
    def _constructor_sliced(self):
        return EntitySeries
    
    @classmethod
    def load(cls, db):
        records = db.get(where={'item': 1})
        docs = [
            {
                'id': id, 
                **json.loads(r), 
            } 
            for id, r, m in zip(records['ids'], records['documents'], records['metadatas'])
        ]
        c = Collection(docs)
        c.db = db
        return c
    
    def embedding_query(self, *texts, ids=None, where=None, threshold=0.1, limit=None, **kwargs):
        texts = [t for t in texts if t is not None]
        
        scores = {}
        if len(texts) == 0:
            results = self.db.get(ids=ids, where=where, **kwargs)
            for id, m in zip(results['ids'], results['metadatas']):
                if m.get('item') != 1:
                    id = m.get('item_id')
                if id not in scores:
                    scores[id] = 1
                else:
                    scores[id] += 1
        else:
            results = self.db.query(query_texts=texts, where=where, **kwargs)
            for i in range(len(results['ids'])):
                for id, d, m in zip(results['ids'][i], results['distances'][i], results['metadatas'][i]):
                    if m.get('item') != 1:
                        id = m.get('item_id')
                    if id not in scores:
                        scores[id] = 1 - d
                    else:
                        scores[id] += 1 - d
        
        try:
            filtered_scores = {k: v for k, v in scores.items() if v >= threshold}
            sorted_ids = sorted(filtered_scores, key=filtered_scores.get, reverse=True)
            results = self[self['id'].isin(sorted_ids)].set_index('id').loc[sorted_ids].reset_index()
            logger.info(f'Found {len(results)} results for query: {texts}')
            if limit is not None:
                return results.head(limit)
            else:
                return results
        except KeyError as e:
            logger.error(f'Failed to parse query results: {e}')
            return None
    
    def __call__(self, *texts, where=None, **kwargs) -> Any:
        return self.embedding_query(*texts, where=where, **kwargs)
    
    @property
    def name(self):
        return self.db.name
    
    @property
    def objects(self):
        if self.empty:
            return []
        if hasattr(self, 'db'):
            ids = self['id'].values.tolist()
            d = self.db.get(ids=ids)
            m = {id: metadata for id, metadata in zip(d['ids'], d['metadatas'])}
            schemas = {
                id: json.loads(metadata['schema']) for id, metadata in m.items()
                    if 'schema' in metadata and metadata['schema'] is not None
            }
            return [
                create_entity_from_schema(
                    schemas.get(r['id']),
                    {
                        k: v for k, v in r.items() if (len(v) if isinstance(v, list) else pd.notnull(v))
                    },
                    base=Entity,
                ) 
                for r in self.to_dict('records')
            ]
        else:
            return [
                create_entity_from_schema(
                    self.schema or {},
                    {
                        k: v for k, v in r.items() if pd.notnull(v)
                    },
                    base=Entity,
                ) 
                for r in self.to_dict('records')
            ]
    
    @property
    def first(self):
        objects = self.objects
        if len(objects) == 0:
            return None
        else:
            return objects[0]
    
    def delete(self, *items):
        self.db.delete(ids=[i.id.replace(' ', '') for i in items])
        for item in items:
            self.db.delete(where={'item_id': item.id})
        self.drop(self[self['id'].isin([i.id for i in items])].index, inplace=True)
        logger.info(f'Deleted {len(items)} items from {self.name}')

    def embed(self, *items, **kwargs):
        records = self._create_records(*items, **kwargs)
        if len(records) == 0:
            raise ValueError('No items to embed')

        ids = [r['id'] for r in records]
        self.db.upsert(
            ids=ids,
            documents=[r['document'] for r in records],
            metadatas=[r['metadata'] for r in records],
        )

        if self.empty:
            new_items = [r for r in records if r['metadata']['item'] == 1]
        else:
            new_items = [
                r for r in records 
                if r['id'] not in self['id'].values
                and r['metadata']['item'] == 1
            ]
        docs = [{'id': r['id'], **json.loads(r['document'])} for r in new_items]
        df = pd.concat([self, Collection(docs)], ignore_index=True)
        self.drop(self.index, inplace=True)
        for column in df.columns:
            self[column] = df[column]
        logger.info(f'Embedded {len(new_items)} items into {self.name}')
        return self

    def _create_records(self, *items, **kwargs):
        records = []

        def _field_serializer(obj):
            if isinstance(obj, Enum):
                return obj.value
            elif isinstance(obj, Entity):
                return { 'id': obj.id, 'type': obj.type }
            raise TypeError(f"Type {type(obj)} not serializable")

        def _serializer(obj):
            if isinstance(obj, Enum):
                return obj.value
            elif isinstance(obj, Entity):
                record = { 'id': obj.id, 'type': obj.type }
                for name, field in obj.model_dump().items():
                    if name in ['id', 'type']:
                        continue
                    f = obj.model_fields.get(name)
                    if f is None:
                        logger.error(f'Field {name} not found in {obj.__class__}')
                        continue
                    if isinstance(f.annotation, type) and issubclass(f.annotation, Entity):
                        field = _field_serializer(getattr(obj, name))
                    if f.field_info.extra.get('embed', True) == False:
                        continue
                    record[name] = field
            raise TypeError(f"Type {type(obj)} is not serializable")

        def _schema_serializer(obj):
            if isinstance(obj, Enum):
                return obj.value
            elif isinstance(obj, PydanticUndefinedType):
                return None
            elif isinstance(obj, BaseModel):
                return obj.model_json_schema()
            raise TypeError(f"Type {type(obj)} not serializable", obj)

        for item in items:
            now = datetime.now().isoformat()
            
            if isinstance(item, str):
                item = Entity(type='string', value=item)
            
            if isinstance(item, dict):
                pass

            for name, field in item.model_dump().items():
                if name in ['id', 'type']:
                    continue

                f = item.model_fields.get(name)
                if f is None:
                    continue

                if isinstance(f.annotation, type) and issubclass(f.annotation, Entity):
                    logger.debug(f'Field {name} is an Entity')
                if f.json_schema_extra and f.json_schema_extra.get('embed', True) == False:
                    continue
                if isinstance(field, int) or isinstance(field, float) or isinstance(field, bool):
                    continue

                # TODO: Handle nested fields
                document = json.dumps({name: field}, default=_serializer)

                field_record = {
                    'id': f'{item.id}_{name}',
                    'document': document,
                    'metadata': {
                        'field': name,
                        'collection': self.name,
                        'item': 0,
                        'item_id': item.id,
                        'created_at': now,
                    },
                }
                records.append(field_record)

            doc = { k: v for k, v in item.model_dump().items() if k not in ['id'] }
            for k, v in doc.items():
                # if v represents an Entity field then create records for it and replace it with a reference
                # use model_fields to check if the current v is an Entity
                f = item.model_fields.get(k)
                if f is None:
                    continue
                if v is None:
                    continue
                if isinstance(f.annotation, type) and issubclass(f.annotation, Entity):
                    doc[k] = _field_serializer(getattr(item, k))
                    records += self._create_records(getattr(item, k))

            doc_record = {
                'id': item.id,
                'document': json.dumps(doc, default=_serializer),
                'metadata': {
                    'collection': self.name,
                    'type': item.type,
                    'item': 1,
                    'schema': json.dumps(item.schema(), default=_schema_serializer),
                    'created_at': now,
                },
            }
            records.append(doc_record)
        
        return records


class CollectionEntity(Entity):
    type: str = 'collection'
    name: str = None
    description: str = None

    def __init__(self, name, description=None, records=None, **kwargs):
        super().__init__(
            name=name, description=description, records=records, **kwargs
        )