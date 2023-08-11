from typing import Callable, List

from .collection import Collection 
from .world import World, Session


def prompt(instructions=None, input=None, output=None, prompt=None, context=None, template=None, llm=None, examples=None, num_examples=1, history=None, tools=None, dryrun=False, retries=3, debug=False, silent=False, **kwargs):
    kwargs = dict(
        instructions=instructions,
        input=input,
        output=output,
        prompt=prompt,
        llm=llm,
        context=context,
        examples=examples,
        num_examples=num_examples,
        history=history,
        tools=tools,
        template=template,
        debug=debug,
        dryrun=dryrun,
        silent=silent,
        retries=retries,
        store=store,
    )
    return DEFAULT_SESSION.prompt(**kwargs)


def chain(*steps, **kwargs):
    return DEFAULT_SESSION.chain(*steps, **kwargs)


def store(*items, collection=None, **kwargs) -> Collection:
    return DEFAULT_SESSION.store(*items, collection=collection, **kwargs)


def query(*texts, field=None, where=None, collection=None, **kwargs) -> Collection:
    return DEFAULT_SESSION.query(
        *texts, field=field, where=where, collection=collection, **kwargs)


def collection(name=None) -> Collection:
    return DEFAULT_SESSION.collection(name)


def evaluate(*testcases, **kwargs) -> Collection:
    return DEFAULT_SESSION.evaluate(*testcases, **kwargs)


def history(query=None, **kwargs):
    if query is not None:
        return DEFAULT_SESSION.history(query, **kwargs)
    else:
        return DEFAULT_SESSION.history


def session() -> Session:
    return DEFAULT_SESSION


def run(world=None, **kwargs):
    if world is None:
        world = DEFAULT_WORLD
    return world(**kwargs)


DEFAULT_WORLD = None
def set_default_world(world):
    global DEFAULT_WORLD
    DEFAULT_WORLD = world


DEFAULT_SESSION = None
def set_default_session(session):
    global DEFAULT_SESSION
    DEFAULT_SESSION = session


Embedding = List[float]
EmbedFunction = Callable[[List[str]], List[Embedding]]


def load_app():
    import os
    import sys
    module_path = os.path.abspath(os.path.join('..'))
    if module_path not in sys.path:
        sys.path.append(module_path)
    
    from app import create_app
    return create_app()


def load(llm=None, ef=None, logger=None, log_format='notebook', **kwargs):
    app = load_app()
    session = app.world.create_session()
    set_default_session(session)


def init(llm=None, ef=None, logger=None, log_format='notebook', **kwargs):
    w = World('test', llm=llm, ef=ef, logger=logger, **kwargs)
    session = w.create_session(log_format=log_format)
    set_default_world(w)
    set_default_session(session)
