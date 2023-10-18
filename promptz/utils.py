import uuid
from enum import Enum
from typing import *
from typing import _GenericAlias
import jsonschema
from pydantic import BaseModel, create_model
from IPython.display import display, HTML


JSON_TYPE_MAP: Dict[str, Type[Union[str, int, float, bool, Any]]] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict,
    "array": list,
}

PYTYPE_TO_JSONTYPE: Dict[Type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    dict: "object",
    list: "array",
}


class Entity(BaseModel):
    id: str = None
    type: str = None

    class Config:
        extra = 'allow'
        arbitrary_types_allowed = True
    
    def __init__(self, id=None, **data):
        if 'type' not in data:
            data['type'] = self.__class__.__name__.lower()
        super().__init__(**{'id': id or str(uuid.uuid4()), **data})
    
    @classmethod
    def generate_schema_for_field(cls, name, field_type: Any, default=None):
        return_list = False
        definitions = {}

        print('generate_schema_for_field', name, field_type, default)
        
        if _is_list_type(field_type):
            print('list', field_type)
            field_type = get_args(field_type)[0]
            return_list = True
        
        # Handle enums
        if isinstance(field_type, type) and issubclass(field_type, Enum):
            print('enum', field_type, return_list)
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
                    "properties": default.schema() if default is not None else {}
                }
            schema = {"$ref": f"#/definitions/{field_type.__name__}"} 

        if return_list:
            schema = {
                "type": "array",
                "items": schema
            } 

        if default:
            schema['default'] = default
        return schema, definitions, []
    
    @classmethod
    def schema(cls, by_alias: bool = True, **kwargs):
        properties = {}
        required = []
        definitions = {}

        for field_name, field_info in cls.__fields__.items():
            try:
                print('schema field', field_name, field_info.type_, cls.__annotations__)
                type_ = cls.__annotations__.get(field_name, field_info.type_)
                field, defs, reqs = cls.generate_schema_for_field(field_name, type_, field_info.default)
                properties[field_name] = field
                definitions = {**definitions, **defs}
            except Exception as e:
                print('schema field failed', field_name, e)
            
            if field_info.required:
                required.append(field_name)
            required += reqs

        # Construct the base schema
        base_schema = {
            "title": cls.__name__,
            "type": "object",
            "properties": properties,
            "definitions": definitions,  # Include definitions for references
            "required": required,
        }

        return base_schema
    
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


def _is_list(schema):
    return schema.get('type') == 'array'


def _is_list_type(type_hint):
    origin = get_origin(type_hint)
    return origin is list or (origin is List and len(get_args(type_hint)) == 1)


def _get_title(schema):
    return schema.get('title', schema.get('items', {}).get('title', 'Entity'))


def _get_properties(schema):
    properties = schema.get('properties', {}) if not _is_list(schema) else schema.get('items', {}).get('properties', {})
    return properties


def _get_field_type(field_info, definitions):
    field_type = field_info.get('type')
    if field_type is None:
        ref = field_info.get('$ref')
        if ref is None:
            ref = field_info.get('allOf', [{}])[0].get('$ref')
        if ref is None:
            return str
        ref_name = ref.split('/')[-1]
        field_type = ref_name
        definition = definitions.get(ref_name)
        if 'enum' in definition:
            members = {v: v for v in definition['enum']}
            E = Enum(definition.get('title', ref_name), members)
            return E
        else:
            M = create_model_from_schema(definition)
            return M

    if field_type == 'array':
        info = field_info.get('items', {})
        return List[_get_field_type(info, definitions)]
    return JSON_TYPE_MAP[field_type]


def _create_field(field_info, definitions, required=False):
    field_type = _get_field_type(field_info, definitions)
    field_default = field_info.get('default', ... if required else None)
    return (field_type, field_default)


def model_to_json_schema(model):
    """
    Convert a Pydantic BaseModel or Python data type to a JSON schema.

    Args:
        model: A Pydantic BaseModel, a Python data type, a list of BaseModel instances, or a dictionary.

    Returns:
        dict: A JSON schema representation of the input model.

    This function takes various types of input and converts them into a JSON schema representation:

    - If `model` is a Pydantic BaseModel, it extracts its schema using `model.schema()`.

    - If `model` is a Python data type (e.g., str, int, float), it maps it to the corresponding JSON type.

    - If `model` is a list of Pydantic BaseModels, it generates a JSON schema for an array of the BaseModel's schema.

    - If `model` is a dictionary, it is returned as is.

    Example:
    >>> from pydantic import BaseModel
    >>> class Person(BaseModel):
    ...     name: str
    ...     age: int
    ...
    >>> schema = model_to_json_schema(Person)
    >>> print(schema)
    {
        'type': 'object',
        'properties': {
            'name': {'type': 'string'},
            'age': {'type': 'integer'}
        },
        'required': ['name']
    }
    """
    output = None
    if isinstance(model, list):
        inner = model[0]
        if issubclass(inner, BaseModel):
            schema = inner.schema()
            output = {
                'type': 'array',
                'items': schema,
                'definitions': schema.get('definitions', {})
            }
        else:
            output = {
                'type': 'array',
                'items': {
                    'type': PYTYPE_TO_JSONTYPE[inner]
                }
            }
    elif isinstance(model, dict):
        output = model
    elif isinstance(model, BaseModel):
        output = model.schema()
    elif isinstance(model, type):
        if issubclass(model, BaseModel):
            output = model.schema()
    
    return output


def create_model_from_schema(schema):
    """
    Create a Pydantic BaseModel from a JSON schema.

    Args:
        schema (dict): The JSON schema to create the Pydantic model from.

    Returns:
        pydantic.BaseModel: A Pydantic data model class generated from the schema.

    This function takes a JSON schema and generates a Pydantic BaseModel class
    with fields corresponding to the properties defined in the schema. It
    also handles definitions and required fields.

    If the schema doesn't specify a 'type' field, it defaults to 'Entity'.

    Example:
    >>> schema = {
    ...     'title': 'Person',
    ...     'type': 'object',
    ...     'properties': {
    ...         'name': {'type': 'string'},
    ...         'age': {'type': 'integer'}
    ...     },
    ...     'required': ['name']
    ... }
    >>> Person = create_model_from_schema(schema)
    >>> person = Person(name='Alice', age=30)
    >>> person.name
    'Alice'
    >>> person.age
    30
    """
    properties = _get_properties(schema)
    definitions = schema.get('definitions', {})
    required = schema.get('required', [])
    fields = {
        name: _create_field(field_info, definitions, name in required)
        for name, field_info in properties.items()
    }
    if 'type' not in fields:
        fields['type'] = (str, ...)
    return create_model(schema.get('title', 'Entity').capitalize(), **fields, __base__=Entity)


def create_entity_from_schema(schema, data):
    """
    Create a Pydantic data entity from a JSON schema and input data.

    Args:
        schema (dict): The JSON schema that defines the structure of the entity.
        data (dict or list): The input data to populate the entity. For a single entity, provide a dictionary.
                             For a list of entities, provide a list of dictionaries.

    Returns:
        pydantic.BaseModel or List[pydantic.BaseModel]: A Pydantic data entity or a list of entities generated
                                                      from the schema and input data.

    This function takes a JSON schema and input data and creates a Pydantic data entity or a list of entities
    based on the schema and data provided. It handles properties, definitions, and optional fields defined
    in the schema.

    If the schema defines an entity as a list, the input data should be a list of dictionaries. Each dictionary
    represents an entity. If 'id' is not provided for each entity, it will be generated using a random UUID.

    If the schema defines an entity as an object (not a list), the input data should be a dictionary representing
    a single entity. If 'id' is not provided, it will be generated using a random UUID.

    Example:
    >>> schema = {
    ...     'title': 'Person',
    ...     'type': 'object',
    ...     'properties': {
    ...         'name': {'type': 'string'},
    ...         'age': {'type': 'integer'}
    ...     },
    ...     'required': ['name']
    ... }
    >>> data = {'name': 'Alice', 'age': 30}
    >>> person = create_entity_from_schema(schema, data)
    >>> person.name
    'Alice'
    >>> person.age
    30

    >>> schema_list = {
    ...     'title': 'People',
    ...     'type': 'array',
    ...     'items': {
    ...         'type': 'object',
    ...         'properties': {
    ...             'name': {'type': 'string'},
    ...             'age': {'type': 'integer'}
    ...         },
    ...         'required': ['name']
    ...     }
    ... }
    >>> data_list = [{'name': 'Alice', 'age': 30}, {'name': 'Bob', 'age': 25}]
    >>> people = create_entity_from_schema(schema_list, data_list)
    >>> len(people)
    2
    >>> people[0].name
    'Alice'
    >>> people[1].age
    25
    """

    if _is_list(schema):
        data = [
            {**o, 'id': str(uuid.uuid4()) if o.get('id') is None else o['id']}
            for o in data
        ]
    else:
        if data.get('id') is None:
            data['id'] = str(uuid.uuid4())
    
    definitions = schema.get('definitions', {})
    for name, field in schema.get('properties', {}).items():
        _type = _get_field_type(field, definitions)
        if isinstance(_type, type) and issubclass(_type, Enum):
            if data.get(name):
                data[name] = data[name].name.lower()
        elif getattr(_type, '__origin__', None) == list and isinstance(_type.__args__[0], type) and issubclass(_type.__args__[0], Enum):
            if data.get(name):
                data[name] = [d.name.lower() for d in data[name]]
    
    # TODO: need to somehow handle nested entities which should be stored as IDs
    # currently the schema is correct in that it defines the desired type as a string
    # however, the entity needs to be loaded when the parent entity is loaded
    
    jsonschema.validate(data, schema)
    m = create_model_from_schema(schema)
    defaults = {
        'type': _get_title(schema),
    }
    if _is_list(schema):
        return [m(**{**defaults, **o}) for o in data]
    else:
        return m(**{**defaults, **data})
