import random
import json
import uuid
import textwrap
from typing import * 
import jsonschema
from pydantic import BaseModel
from openai.error import RateLimitError
from jinja2 import Template as JinjaTemplate

from .collection import Collection
from .logging import *
from .models import ChatLog, LLM, MockLLM
from .utils import Entity, model_to_json_schema, create_entity_from_schema


class MaxRetriesExceeded(Exception):
    pass


E = TypeVar('E', bound=BaseModel)

class Template(Entity):
    
    template = """
    INSTRUCTIONS
    ---
    {{instructions}}
    {{format}}
    {{examples}}
    {{input}}
    {{output}}
    """

    input_template = """
    INPUT
    ---
    {{input}}
    END_INPUT
    """

    output_template = """
    OUTPUT
    ---
    {{output}}
    """

    example_template = f"""
    EXAMPLES
    ---
    {input_template}
    {output_template}
    END_EXAMPLES
    """

    format_template = """
    FORMAT INSTRUCTIONS
    ---
    {% if list_output %}
    Return a list of valid JSON objects with the fields described below.
    {% else %}
    Return the output as a valid JSON object with the fields described below. 
    {% endif %}
    {% for field in fields %}
    - {{field.name}} (type: {{field.type_}}, required: {{field.required}}){% if field.description != None %}: {{field.description}}{% endif %}
    {% endfor %}

    Make sure to use double quotes and avoid trailing commas!
    Ensure any required fields are set, but you can use the default value 
    if it's defined and you are unsure what to use. 
    If you are unsure about any optional fields use `null` or the default value,
    but try your best to fill them out.
    END_FORMAT_INSTRUCTIONS
    """

    type: str = 'template'
    name: str = None
    instructions: str = None
    num_examples: int = 1
    examples: List = None
    _input: str = None
    _output: str = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.instructions = textwrap.dedent(self.instructions or '')
        if hasattr(self, 'input') and self.input is not None:
            self._input = json.dumps(self.input.schema())
        if hasattr(self, 'output') and self.output is not None:
            self._output = json.dumps(self.output.schema())
    
    def schema(self, by_alias: bool = True):
        schema = super().schema(by_alias=by_alias)
        if self._input is not None:
            schema['properties']['input'] = json.loads(self._input)
        if self._output is not None:
            schema['properties']['output'] = json.loads(self._output)
        return schema


class TemplateRunner:
    template: Template
    llm: LLM = MockLLM()

    def __init__(self, llm=None, logger=None, debug=False, silent=False, name=None):
        self.logger = logger
        self.llm = llm or self.llm
    
    def parse(self, x):
        if isinstance(x, BaseModel):
            return {k: v for k, v in x.dict().items() if k not in ['id', 'type']}
        elif isinstance(x, Entity):
            return {k: v for k, v in x.object.dict().items() if k not in ['id', 'type']}
        elif isinstance(x, Collection):
            return [
                {k: v for k, v in y.dict().items() if k not in ['id', 'type']}
                for y in x.objects
            ]
        elif isinstance(x, str):
            return x
        elif isinstance(x, dict):
            return {k: self.parse(v) for k, v in x.items()}
        elif isinstance(x, list):
            return [self.parse(y) for y in x]
        elif x is None:
            return {}
        else:
            return x
    
    def render(self, t, x, **kwargs):
        input_template = JinjaTemplate(t.input_template)
        input = input_template.render(**x) if len(x) > 0 else ''
        output_template = JinjaTemplate(t.output_template)
        output = output_template.render(**x) if len(x) > 0 else ''
        vars = {
            **x,
            'instructions': t.instructions,
            'examples': self.render_examples(t),
            'format': self.render_format(t, x),
            'input': input,
            'output': output,
        }
        template = JinjaTemplate(t.template)
        output = template.render(**vars)
        return output
    
    def format_field(self, name, field, definitions, required):
        description = field.get('description', '')
        options = ''

        if field.get('type') == 'array':
            item_type = field.get('items', {}).get('type', None)
            if item_type is None:
                ref = field.get('items', {}).get('$ref', None)
                ref = ref.split('/')[-1]
                definition = definitions.get(ref, {})
                type_ = f'{definition.get("title", ref)}[]'
                type_ = 'string'

                if 'enum' in definition:
                    options += f'''
                    Select any relevant options from: {", ".join(definition["enum"])}
                    '''
            else:
                type_ = f'{item_type}[]'
        elif field.get('type') == 'enum':
            type_ = 'str'
            options += f'''Select only one option: {", ".join([
                member.value for member in field.type_
            ])}'''
        else:
            type_ = field.get('type', 'str')

        if len(options) > 0:
            description += ' ' + options

        return {
            'name': name,
            'title': field.get('title', None),
            'type_': type_,
            'default': field.get('default', None),
            'description': description.strip(),
            'required': name in required,
        }
    
    def render_format(self, t, x, **kwargs):
        if t.output is None:
            return ''
        
        list_output = False

        output = model_to_json_schema(t.output)
        fields = []
        if output.get('type', None) == 'array':
            properties = output.get('items', {}).get('properties', {})
            definitions = output.get('items', {}).get('definitions', {})
            required = output.get('items', {}).get('required', [])
            list_output = True
        elif output.get('type', None) == 'object':
            properties = output.get('properties', {})
            definitions = output.get('definitions', {})
            required = output.get('required', [])
        
        for name, property in properties.items():
            f = self.format_field(name, property, definitions, required)
            fields += [f]
        
        format_template = JinjaTemplate(t.format_template)
        return format_template.render({
            'fields': [field for field in fields if field is not None], 
            'list_output': list_output,
        })
    
    def render_examples(self, t, **kwargs):
        if t.examples is None or len(t.examples) == 0:
            return ''
        examples = [
            {
                'input': json.dumps(self.parse(i)),
                'output': json.dumps(self.parse(o)),
            }
            for i, o in random.sample(t.examples, t.num_examples)
        ]
        example_template = JinjaTemplate(t.example_template)
        return '\n'.join([
            example_template.render(**e) for e in examples
        ])
    
    def process(self, t, x, output, **kwargs):
        if t.output is None:
            return output
        out = json.loads(output)
        schema = model_to_json_schema(t.output)
        entities = create_entity_from_schema(schema, out)
        return entities
    
    def dict(self):
        return {
            'id': self.id,
            'type': 'template',
            'name': self.name or None,
            'instructions': self.instructions,
            'input': self.input,
            'output': self.output,
        }
    
    def __call__(self, t, x, **kwargs):
        return self.forward(t, x, **kwargs)
    
    def forward(self, t, x, retries=3, dryrun=False, **kwargs):
        if retries and retries <= 0:
            e = MaxRetriesExceeded(f'{self.name} failed to forward {x}')
            self.logger.error(e)
            raise e
        
        if dryrun:
            self.logger.debug(f'Dryrun: {t.output}')
            llm = MockLLM(output=t.output)
        else:
            llm = self.llm
        
        px = self.parse(x)
            
        prompt_input = self.render(t, {'input': px})
        self.logger.log(INSTRUCTIONS, t.instructions)
        if t.examples: self.logger.log(EXAMPLES, self.render_examples(t))
        if len(px): self.logger.log(INPUT, px)
        self.logger.debug(f'FULL INPUT: {prompt_input}')
        response = llm.generate(prompt_input)
        if t.output: self.logger.log(FORMAT_INSTRUCTIONS, self.render_format(t, px))
        try:
            self.logger.log(OUTPUT, response.raw)
            response.content = self.process(t, px, response.raw, **kwargs)
        except jsonschema.exceptions.ValidationError as e:
            self.logger.warn(f'Output validation failedcls: {e} {response.content}')
            return self.forward(t, x, retries=retries-1, **kwargs)
        except json.JSONDecodeError as e:
            self.logger.warn(f'Failed to decode JSON from {response.content}: {e}')
            return self.forward(t, x, retries=retries-1, **kwargs)
        except RateLimitError as e:
            self.logger.warn(f'Hit rate limit for {self}: {e}')
            return self.forward(t, x, retries=retries-1, **kwargs)
        self.logger.log(METRICS, response.metrics)
        return response


class ChatPrompt(Template):
    '''
    You are a helpful assistant.
    '''

    template = '''
    {{input}}
    {{output}}
    '''