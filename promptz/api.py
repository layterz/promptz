from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .world import World 
from .collection import Collection, Query
from .template import TemplateDetails, Template


class PromptInput(BaseModel):
    input: Any = None


class API:
    world: World

    def __init__(self, world, logger=None):
        self.world = world
        self.logger = logger or world.logger.getChild('api')
        self.fastapi_app = FastAPI()

        @self.fastapi_app.post("/prompt")
        async def run_prompt(details: TemplateDetails):
            print('running prompt', details)
            session = self.world.create_session()
            template = Template(**details.dict())
            response = session.prompt(**{**dict(template), 'input': {}})
            return {"response": response}
        
        @self.fastapi_app.get("/templates")
        async def get_templates():
            r = self.world.templates()
            if r is None:
                templates = []
            else:
                templates = r.objects

            return {"response": templates}

        @self.fastapi_app.get("/templates/{id}")
        async def get_template(id: str):
            history = self.world.history()
            if history is None or history.empty:
                results = []
            else:
                results = history[history['template'] == id].to_dict('records')
            template = self.world.templates(ids=[id]).first
            if template is None:
                raise HTTPException(status_code=404, detail="Template not found")
            return {'details': template, 'results': results}
        
        @self.fastapi_app.post("/templates")
        async def create_template(details: TemplateDetails):
            t = self.world.create_template(details)
            return t.id

        @self.fastapi_app.post("/templates/{id}/run")
        async def run_template(id: str, input: PromptInput = None):
            session = self.world.create_session()
            template = self.world.templates(ids=[id]).first
            if template is None:
                raise HTTPException(status_code=404, detail="Template not found")
            response = session.prompt(**{**dict(template), 'input': input})
            return {"response": response}
        
        @self.fastapi_app.get("/history")
        async def get_history():
            if self.world.history.empty:
                return {'response': []}
            else:
                return {'response': self.world.history().objects}

        @self.fastapi_app.get("/inbox")
        async def get_collections():
            return {"response": []}

        @self.fastapi_app.get("/conversations")
        async def get_collections():
            return {"response": []}

        @self.fastapi_app.get("/collections")
        async def get_collections():
            return {"response": [c for c in self.world.collections().objects]}

        @self.fastapi_app.get("/collections/{name}")
        async def get_collection(name: str):
            try:
                c = self.world.collections[name]
                r = Collection.load(c)()
                if r is None:
                    return {"response": []}
                else:
                    return {"response": r.objects}
            except KeyError:
                raise HTTPException(status_code=404, detail="Collection not found")

        @self.fastapi_app.get("/systems")
        async def get_systems():
            return {"response": self.world.systems.keys()}
        
        @self.fastapi_app.get("/systems/{name}")
        async def get_system(name: str):
            return {"response": self.world.systems[name]}
        
        @self.fastapi_app.post("/systems/run")
        async def run_systems():
            session = self.world.create_session()
            return {"response": self.world(session)}
        
        @self.fastapi_app.post("/query")
        async def query(query: Query):
            session = self.world.create_session()
            response = session.query(query.query, where=query.where, collection=query.collection)
            return {"response": response}
        
        @self.fastapi_app.get("/notebooks")
        async def get_notebooks():
            return {"response": self.world.notebooks}
        
        @self.fastapi_app.get("/notebooks/{name}")
        async def get_notebook(name: str):
            return {"response": self.world.notebooks[name]}
        
        @self.fastapi_app.get("/chats")
        async def get_chats():
            return {"response": {}}