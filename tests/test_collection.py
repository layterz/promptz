import pytest

from promptx.collection import *
from promptx.utils import Entity


class User(Entity):
    name: str
    age: int


def test_objects_are_returned_with_correct_schema():
    user = User(name="test", age=20)
    collection = Collection([dict(user)])
    collection.schema = User.schema()

    assert len(collection.objects) == 1
    assert collection.first.name == "test"

def test_embedding_an_entity(mocker):
    user = User(name="test", age=20)
    db = mocker.Mock(spec=VectorDB)
    db.name = 'test'
    db.get.return_value = {'ids': [user.id], 'documents': [user.model_dump_json()], 'metadatas': [{'schema': json.dumps(user.model_json_schema())}]}
    collection = Collection.load(db)
    collection.embed(user)

    assert len(collection.objects) == 1
    assert collection.first.name == "test"