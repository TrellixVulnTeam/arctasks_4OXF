import os
import shutil

from .arctask import arctask
from .runners import local
from .util import abort, as_list, print_header, print_error, print_success, print_warning


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


@arctask(configured='dev')
def lint(ctx):
    """Check source files for issues.

    For Python code, this uses the flake8 package, which wraps pep8 and
    pyflakes. To configure flake8 for your project, add a setup.cfg file
    with a [flake8] section.

    TODO: Lint JS?
    TODO: Lint CSS?

    """
    print_header('Checking for Python lint in {package}...'.format(**ctx))
    result = local(ctx, 'flake8 {package}', echo=False, abort_on_failure=False)
    if result.failed:
        pieces_of_lint = len(result.stdout.strip().splitlines())
        print_error(pieces_of_lint, 'pieces of Python lint found')
    else:
        print_success('Python is clean')


@arctask(configured='dev')
def npm_install(ctx, modules=None, force=False):
    """Install node modules via npm into ./node_modules.

    By default, any modules that are already installed will be skipped.
    Pass --force to install all specified modules.

    """
    result = local(ctx, 'which npm', echo=False, hide='stdout', abort_on_failure=False)
    if result.failed:
        abort(1, 'node and npm must be installed first')
    modules = as_list(modules)
    if not force:
        modules = [
            m for m in modules if not os.path.isdir(os.path.join(ctx.cwd, 'node_modules', m))]
        if not modules:
            print_warning('All specified modules already installed; maybe pass --force?')
    if modules:
        local(ctx, ('npm install', modules), hide='stdout')
