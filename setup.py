from setuptools import setup

with open('requirements.txt') as f:
    requirements = f.read().splitlines()

setup(
    name='promptx',
    version='0.0.1',
    description='An AI framework',
    packages=['promptx'],
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "px = promptx.cli:main",
        ],
    },
)