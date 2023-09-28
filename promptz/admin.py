import os
import random
import json
from urllib.parse import urljoin
import uuid
import requests
import pandas as pd
from pydantic import BaseModel
from textblob import Word
import dash
from dash import Dash, html, dcc, dash_table, no_update, page_container, page_registry, register_page, Output, Input, State
from dash.exceptions import PreventUpdate
from dash.dependencies import ALL
import dash_bootstrap_components as dbc

from promptz.world import World
from promptz.template import Template


API_URL = 'http://localhost:8000'


class Index(BaseModel):
    
    class Config:
        arbitrary_types_allowed = True

    id: str
    app: Dash
    collection: str
    columns: list = None

    def __init__(self, app, collection, columns=None, **kwargs):
        super().__init__(
            id=str(uuid.uuid4()),
            app=app,
            collection=collection,
            columns=columns,
            **kwargs,
        )
        
        @self.app.callback(
            Output(
                f'{self.id}-query-results', 'children',
            ),
            [
                Input(f'{self.id}-search-submit', 'n_clicks'),
            ],
            [
                State(f'{self.id}-search', 'value'),
            ],
        )
        def submit_form(n_clicks, value):
            if n_clicks is None or n_clicks == 0:
                return self.fetch()
            
            return self.fetch(query=value)
    
    def fetch(self, query=None):
        TEXT_MESSAGE_STYLE = {
            'width': '100%',
            'height': '100px',
            'padding': '2rem 0',
            'text-align': 'center',
        }

        if self.collection == '':
            return html.P('No collection specified.', style=TEXT_MESSAGE_STYLE)
        api_path = urljoin(API_URL, self.pathname)
        response = requests.get(api_path, params={'query': query})
        if response.status_code == 200:
            data = response.json()
            l = data.get('list', [])
        else:
            raise Exception(f'Error getting index {self.collection}: {response.status_code}')
        
        if len(l) == 0:
            return html.P('Nothing to see here.', style=TEXT_MESSAGE_STYLE),

        df = pd.DataFrame(l)
        df['id'] = df.apply(self.generate_link, axis=1)

        if self.columns is not None:
            df = df[self.columns]
        
        table = dbc.Table.from_dataframe(df)
        return table
    
    @property
    def pathname(self):
        return f'/{self.collection}'

    def generate_link(self, row):
        link = os.path.join(f'/{self.collection}', row['id'])
        return html.A(row.get('id'), href=link, target='_self')

    def render(self, data=None, **kwargs):
        RESULTS_STYLE = {
            'border-top': '1px solid lightgray',
        }

        results = html.Div([], id=f'{self.id}-query-results', style=RESULTS_STYLE)

        search = dbc.Input(
            name='search',
            placeholder='Search',
            id=f'{self.id}-search',
        )

        search_input = dbc.Form([
            dbc.Row([
                dbc.Col([
                    search,
                ], width=9),
                dbc.Col([
                    dbc.Button('Submit', id=f'{self.id}-search-submit', n_clicks=0, color='secondary')
                ], width=3)
            ])
        ])

        HEADER_STYLE = {
            'padding': '10px',
        }

        INDEX_STYLE = {
            'background-color': 'white',
            'border-radius': '5px',
        }

        return html.Div(children=[
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H3(self.collection),
                        ],
                        width=3,
                    ),
                    dbc.Col(
                        [
                            html.Div(
                                search_input,
                            ),
                        ],
                        width=9,
                    ),
                ],
                style=HEADER_STYLE,
            ),
            dbc.Row(
                results,
            ),
            dcc.Interval(
                id=f'fetch-interval',
                n_intervals=1,  # Set an interval that triggers once
                max_intervals=1  # Only trigger once
            ),
            dcc.Store(id=f'{self.id}-data-store'),
        ], style=INDEX_STYLE)


class AdminPage(BaseModel):
    app: Dash
    name: str
    path: str = None
    path_template: str = None
    menu: bool = False
    icon: str = None
    api_path: str = None

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, app, name, path=None, path_template=None, menu=False, icon=None):
        super().__init__(
            app=app,
            name=name,
            path=path,
            path_template=path_template,
            menu=menu,
            icon=icon,
        )
        self.register_callbacks()

    def layout(self, **kwargs):
        content = self.render(**kwargs)
        return html.Div(children=[
            dcc.Interval(
                id='fetch-interval',
                interval=1,  # Set an interval that triggers once
                max_intervals=1  # Only trigger once
            ),
            content,
        ])
    
    def render(self, **kwargs):
        return html.Div(children=[
            html.H1(self.name),
        ])
    
    def register_callbacks(self):
        pass


class AdminIndexPage(AdminPage):
    index: Index = None
    collection: str = None

    def __init__(self, app, collection, columns=None, **kwargs):
        super().__init__(
            app,
            **kwargs,
        )
        self.collection = collection
        self.index = Index(
            app=self.app, collection=self.collection, columns=columns
        )

    def layout(self):
        content = self.index.render()
        return content


class EntityDetails(BaseModel):
    data: dict

    def render(self, **kwargs):
        data = [
            {'field': k, 'value': v.get('title')} if type(v) == dict else {'field': k, 'value': v}
            for k, v in self.data.items()
            if k not in ['id', 'type', 'name']
        ]
        
        details = html.Div([
            html.H3(self.data.get('name')),
            html.P(self.data.get('type')),
        ])

        list_items = dbc.ListGroup(
            [
                dbc.ListGroupItem(
                    [
                        html.H6(item['field']),
                        html.P(item['value']),
                    ],
                )
                for item in data
            ],
        )

        return html.Div(
            [
                details,
                list_items,
            ],
            style={
                'padding': '1rem',
                'background-color': 'white',
            },
        )


class EntityInputForm(BaseModel):
    
    class Config:
        arbitrary_types_allowed = True

    id: str
    page: str
    app: Dash 

    def __init__(self, app, page, submit, **kwargs):
        super().__init__(
            id=str(uuid.uuid4()),
            app=app,
            page=page,
            **kwargs,
        )
        
        @self.app.callback(
            Output(
                f'{self.id}-form-output', 'children',
            ),
            [
                Input(f'{self.id}-submit', 'n_clicks'),
                Input(f'{self.page}-data-store', 'data'),
            ],
            [
                State({'type': 'form-input', 'field': ALL}, 'value')
            ]
        )
        def submit_form(n_clicks, data, values):
            if n_clicks is None or n_clicks == 0:
                raise PreventUpdate
            
            field_data = {}
            input_schema = json.loads(data.get('details', {}).get('input', '{}'))
            fields = input_schema.get('properties', {}).keys()
            for input_id, input_value in zip(fields, values):
                field_data[input_id] = input_value
            id = data.get('details', {}).get('id')
            return submit(id, field_data)

    def render(self, data=None):
        input_data = data.get('input')
        if input_data is None:
            return None
        input = json.loads(input_data)
        if input is None or input == 'null':
            inputs = [{
                'id': 'input',
                'label': 'Input',
            }]
        else:
            input_schema = {
                name: field
                for name, field in input['properties'].items()
            }
            inputs = []
            for name, field in input_schema.items():
                input = {
                    'id': name,
                    'label': field['title'],
                }
                if field['type'] == 'string':
                    input['type'] = 'text'
                elif field['type'] == 'integer':
                    input['type'] = 'number'
                elif field['type'] == 'boolean':
                    input['type'] = 'checkbox'
                else:
                    input['type'] = 'text'
                
                inputs.append(input)
        
        form = dbc.Form(
            [
                *[
                    html.Div([
                        dbc.Label(input['label']),
                        dbc.Input(
                            id={'type': 'form-input', 'field': input['id']},
                            name=input['label'],
                            type=input['type'],
                            placeholder=f'Enter {input["label"]}',
                        )
                    ])
                    for input in inputs
                ],
                html.Div(
                    dbc.Button('Submit', id=f'{self.id}-submit', n_clicks=0, color='secondary')
                ),
                html.Div(id=f'{self.id}-form-output'),
            ],
            style={
                'padding': '10px',
                'margin': '10px 0',
                'background-color': 'white',
            }
        )
        return form


class AdminEntityPage(AdminPage):
    components: list = None

    def __init__(self, app, components=None, **kwargs):
        super().__init__(
            app,
            **kwargs,
        )
        self.components = components or []
    
    def register_callbacks(self):
        @self.app.callback(
            Output(f'{self.name}-data-store', 'data'),
            Output(f'{self.name}-details', 'children'),
            Output(f'{self.name}-components', 'children'),
            Input('fetch-interval', 'n_intervals'),
            Input('url', 'pathname'),
        )
        def fetch_data(n_intervals, pathname):
            if n_intervals is None or n_intervals == 0:
                return no_update
            api_path = urljoin(API_URL, pathname)
            response = requests.get(api_path)
            if response.status_code == 200:
                data = response.json()
                details = self.render_details(data)
                components = self.render_components(data)
                return data, details, components
            else:
                raise Exception(f'Error getting entity ({api_path}): {response.status_code}')

    def layout(self, **kwargs):
        return html.Div(children=[
            dcc.Location(id='url', refresh=False), 
            dcc.Loading(id='loading', type='default', children=[
                dcc.Store(id=f'{self.name}-data-store'),
                html.Div(id=f'{self.name}-details'),
                html.Div(id=f'{self.name}-components'),
            ]),
            
            dcc.Interval(
                id=f'fetch-interval',
                interval=1,  # Set an interval that triggers once
                max_intervals=1  # Only trigger once
            ),
        ])
    
    def render_details(self, data):
        details = data.get('details')
        if details is None:
            return None
        return EntityDetails(data=details).render()
    
    def render_components(self, data):
        details = data.get('details')
        if details is None:
            return None
        return [
            component.render(details)
            for component in self.components
        ]
    

class TemplateIndex(AdminIndexPage):

    def __init__(self, app, **kwargs):
        super().__init__(
            app,
            'templates',
            name="Templates",
            path="/templates",
            columns=['id', 'name', 'instructions'],
            icon='bi bi-code-slash',
            **kwargs,
        )


class QueryIndex(AdminIndexPage):

    def __init__(self, app, **kwargs):
        super().__init__(
            app,
            name="Queries",
            path="/queries",
            collection='queries',
            icon='bi bi-search',
            **kwargs,
        )


class AgentIndex(AdminIndexPage):

    def __init__(self, app, **kwargs):
        super().__init__(
            app,
            name="Agents",
            path="/agents",
            collection='agents',
            icon='bi bi-robot',
            **kwargs,
        )


class SubscriptionIndex(AdminIndexPage):

    def __init__(self, app, **kwargs):
        super().__init__(
            app,
            name="Subscriptions",
            path="/subscriptions",
            collection='subscriptions',
            icon='bi bi-inbox',
            **kwargs,
        )


class ModelIndex(AdminIndexPage):

    def __init__(self, app, **kwargs):
        super().__init__(
            app,
            name="Models",
            path="/models",
            collection='models',
            icon='bi bi-infinity',
            **kwargs,
        )


class CollectionIndex(AdminIndexPage):

    def __init__(self, app, **kwargs):
        super().__init__(
            app,
            name="Collections",
            path="/collections",
            collection='collections',
            icon='bi bi-database',
            **kwargs,
        )


class Inbox(AdminIndexPage):
    menu: bool = False

    def __init__(self, app, **kwargs):
        super().__init__(
            app,
            name="Inbox",
            path="/inbox",
            collection='inbox',
            icon='bi bi-envelope',
            **kwargs,
        )


class Logs(AdminIndexPage):

    def __init__(self, app, **kwargs):
        super().__init__(
            app,
            name="Logs",
            path="/logs",
            collection='logs',
            icon='bi bi-list',
            **kwargs,
        )


class CollectionPage(AdminIndexPage):

    def __init__(self, app, **kwargs):
        super().__init__(
            app,
            name="Collection",
            path_template="/collections/<id>",
            **kwargs,
        )
    
    def layout(self, id=None):
        return super().layout()


class DetailsPage(AdminEntityPage):

    def __init__(self, app, collection, **kwargs):
        super().__init__(
            app,
            name="Details",
            path_template=f"/{collection}/<id>",
            **kwargs,
        )


class TemplateDetailsPage(AdminEntityPage):

    def __init__(self, app, **kwargs):
        super().__init__(
            app,
            name="Template Details",
            path_template="/templates/<id>",
            **kwargs,
        )
        results_index = Index(
            app=app, 
            collection='logs', 
            columns=['id', 'name', 'instructions']
        )

        def handle_submit(id, data):
            api_path = urljoin(API_URL, f'/templates/{id}/run')
            response = requests.post(api_path, json={'input': data})
            if response.status_code == 200:
                data = response.json()
                return data
            else:
                raise Exception(f'Error submitting form: {response.status_code}')

        input_form = EntityInputForm(
            app=app,
            page=self.name,
            submit=handle_submit,
        )

        components = [
            input_form,
            results_index,
        ]

        self.components = components
    

class CollectionDetailsPage(AdminEntityPage):
    results_index: Index = None

    def __init__(self, app, **kwargs):
        super().__init__(
            app,
            name="Collection Details",
            path_template="/collections/<id>",
            **kwargs,
        )


class Admin:
    world: World

    def __init__(self, world, logger=None):
        self.world = world
        self.logger = logger or world.logger.getChild('admin')
        self.app = Dash(
            world.name, 
            use_pages=True,
            pages_folder='',
            external_stylesheets=[dbc.themes.ZEPHYR, dbc.icons.FONT_AWESOME, dbc.icons.BOOTSTRAP],
        )

        pages = [
            TemplateDetailsPage(self.app),
            CollectionDetailsPage(self.app),

            Inbox(self.app, menu=True),
            QueryIndex(self.app, menu=True),
            SubscriptionIndex(self.app, menu=True),
            TemplateIndex(self.app, menu=True),
            AgentIndex(self.app, menu=True),
            CollectionIndex(self.app, menu=True),
            ModelIndex(self.app, menu=True),
            Logs(self.app, menu=True),
        ]

        for page in pages:
            register_page(page.name, layout=page.layout, path=page.path, path_template=page.path_template)
        
        SIDEBAR_STYLE = {
            "position": "fixed",
            "top": "68px",
            "left": 0,
            "bottom": 0,
            "width": "18rem",
            "padding": "1rem 1rem",
            "background-color": "#fff",
        }

        CONTENT_STYLE = {
            "margin-top": "66px",
            "padding": "1rem 2rem 0 20rem",
            "background-color": "#F5F5F5",
            "width": "100vw",
            "min-height": "100vh",
        }

        menu = [page for page in pages if page.menu]
        nav = dbc.Nav(
            [
                dbc.NavLink(
                    [
                        html.I(className=page.icon),
                        '   ',
                        page_registry[page.name]['name'], 
                    ],
                    href=page_registry[page.name]['relative_path'], 
                    active='exact',
                )
                for page in menu
            ],
            vertical=True,
            pills=True,
        )

        placeholders = [
            "What is the capital of France?",
            "Translate 'hello' to Spanish.",
            "What's the distance between the Earth and the Moon?",
            "Explain the Pythagorean theorem.",
            "Tell me a joke about physics.",
            "List five renewable energy sources.",
            "Write a short poem about the ocean.",
            "How does photosynthesis work?",
            "When was the Declaration of Independence signed?",
            "Who wrote 'Pride and Prejudice'?",
            "Calculate the area of a circle with radius 5.",
            "Recommend a classic sci-fi book.",
            "Describe the plot of 'Moby-Dick'.",
            "What's the chemical formula for water?",
            "Play a trivia game about ancient civilizations.",
            "How do I make a vegetarian lasagna?",
            "Show me breathing exercises for relaxation.",
            "Who was the 16th president of the United States?",
            "Provide a brief history of the Renaissance.",
            "Generate a business idea for eco-friendly products."
        ]

        placeholder = random.choice(placeholders)
        self.app.layout = html.Div([
            dbc.Navbar(
                dbc.Container(
                    children=[
                        dbc.Col(
                            dbc.NavbarBrand(
                                "Promptz",
                                href="/",
                                className="ml-2",
                            ),
                            width=3,
                        ),
                        dbc.Col(
                            dbc.InputGroup([
                                dbc.InputGroupText(
                                    html.I(className="bi bi-chevron-right", style={
                                        'font-size': '1.2rem',
                                        'line-height': '1rem',
                                        'color': 'lightgray',
                                    }),
                                ),
                                dbc.Input(
                                    type="text",
                                    placeholder=placeholder,
                                ),
                            ]),
                            width=6,
                        ),
                        dbc.Col(
                            dbc.NavItem(
                                dbc.NavLink(html.I(className="bi bi-person-circle"), href="/")
                            ),
                            width=3,
                            style={
                                'text-align': 'right',
                                'font-size': '1.5em',
                            },
                        )
                    ],
                    style={
                        'max-width': '100vw',
                        'padding': '0 2rem',
                    }
                ),
                color="white",
                dark=False,
                fixed='top',
                style={
                    'border-bottom': '1px solid lightgray',
                }
            ),
            dbc.Container(
                [
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    nav,
                                ],
                                width=3,
                                style=SIDEBAR_STYLE,
                            ),
                            dbc.Col(
                                [
                                    page_container
                                ], 
                                style=CONTENT_STYLE,
                                width=9,
                            ),
                        ],
                    ),
                ],
                fluid=True,
                style={
                },
            ),
        ])
