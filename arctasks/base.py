import os
import shutil

from .arctask import arctask
from .runners import local


@arctask
def clean(ctx):
    local(ctx, 'find . -name __pycache__ -type d -print0 | xargs -0 rm -r')
    local(ctx, 'find . -name "*.py[co]" -print0 | xargs -0 rm')
    local(ctx, 'rm -rf build')
    local(ctx, 'rm -rf dist')


@arctask(configured='dev')
def install(ctx, requirements='{requirements}', upgrade=False):
    local(ctx, ('{pip}', 'install', '--upgrade' if upgrade else '', '-r', requirements))


@arctask(configured='dev')
def virtualenv(ctx, executable='python3', overwrite=False):
    create = True
    if os.path.exists(ctx.venv):
        if overwrite:
            print('Overwriting virtualenv {venv}'.format(**ctx))
            shutil.rmtree(ctx.venv)
        else:
            create = False
            print('virtualenv {venv} exists'.format(**ctx))
    if create:
        local(ctx, ('virtualenv', '-p', executable, '{venv}'))
        local(ctx, '{pip} install -U setuptools')
        local(ctx, '{pip} install -U pip')
        # The following is necessary for bootstrapping purposes
        local(ctx, '{pip} install invoke=={_invoke.version}')
