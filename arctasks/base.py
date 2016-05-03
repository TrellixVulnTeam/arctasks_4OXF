import os
import shutil
import urllib.request

from .arctask import DEFAULT_ENV, arctask
from .runners import local
from .util import abort, as_list
from .util import print_header, print_error, print_info, print_success, print_warning


@arctask
def clean(ctx):
    local(ctx, 'find . -name __pycache__ -type d -print0 | xargs -0 rm -r')
    local(ctx, 'find . -name "*.py[co]" -print0 | xargs -0 rm')
    local(ctx, 'rm -rf build')
    local(ctx, 'rm -rf dist')


@arctask(configured='dev')
def install(ctx, requirements='{pip.requirements}', upgrade=False):
    local(ctx, ('{bin.pip}', 'install', '--upgrade' if upgrade else '', '-r', requirements))


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
        local(ctx, '{bin.pip} install -U setuptools')
        local(ctx, '{bin.pip} install -U pip')


@arctask(configured='dev')
def lint(ctx, where='{package}'):
    """Check source files for issues.

    For Python code, this uses the flake8 package, which wraps pep8 and
    pyflakes. To configure flake8 for your project, add a setup.cfg file
    with a [flake8] section.

    TODO: Lint JS?
    TODO: Lint CSS?

    """
    print_header('Checking for Python lint in {where}...'.format(where=where))
    result = local(ctx, ('flake8', where), echo=False, abort_on_failure=False)
    if result.failed:
        pieces_of_lint = len(result.stdout.strip().splitlines())
        print_error(pieces_of_lint, 'pieces of Python lint found')
    else:
        print_success('Python is clean')


_npm_install_modules = (
    'bower',
    'less',
    'less-plugin-autoprefix',
    'less-plugin-clean-css',
    'requirejs',
    'uglify-js',
)


@arctask(configured='dev')
def npm_install(ctx, modules=_npm_install_modules, force=False):
    """Install node modules via npm into ./node_modules.

    By default, any modules that are already installed will be skipped.
    Pass --force to install all specified modules.

    """
    result = local(ctx, 'which npm', echo=False, hide='stdout', abort_on_failure=False)
    if result.failed:
        abort(1, 'node and npm must be installed first')
    modules = as_list(modules)
    local(ctx, ('npm install', modules), hide='stdout')


@arctask(configured=DEFAULT_ENV)
def retrieve(ctx, source, destination, overwrite=False, chmod=None):
    """Similar to ``wget``, retrieves and saves a resource.

    If ``destination`` exists, the resource won't be retrieved unless
    ``--overwrite`` is specified.

    If ``destination`` looks like a directory (i.e., it ends with a path
    separator), it will be created if it does not exist. If necessary,
    parent directories will also be created.

    If ``destination`` looks like a file (but isn't an existing
    directory), the directory containing the file will be created
    (in shell terms: ``mkdir -p $(dirname destination)``).

    If ``destination`` is (or looks like) a directory, the base name of
    ``source`` will be joined to it. E.g., for the ``source``
    'http://example.com/pants' and the ``destination`` '/tmp', the
    resource will be saved to '/tmp/pants'.

    If ``chmod`` is specified, the resource will have its mode changed
    after it is saved. The value should be something that's acceptable
    to ``os.chmod`` (e.g., ``0o755``). If ``--chmod`` is passed as a
    string (e.g., from the command line), it must represent an octal
    value (e.g., ``'755'``).

    Returns the absolute path to the saved resource (i.e., the computed
    destination).

    """
    source = source.format(**ctx)
    destination = destination.format(**ctx)
    chmod = int(chmod, 8) if isinstance(chmod, str) else chmod
    make_dir = None

    if os.path.isdir(destination):
        destination = os.path.join(destination, os.path.basename(source))
    elif destination[-1] in (os.sep, '/'):
        # Assume destination is a directory
        make_dir = destination
        destination = os.path.join(destination, os.path.basename(source))
    else:
        # Assume destination is a file path
        make_dir = os.path.dirname(destination)

    f_args = locals()

    if os.path.exists(destination):
        if not overwrite:
            print_warning('{destination} exists; pass --overwrite to re-fetch it'.format(**f_args))
            return destination
        else:
            print_warning('Overwriting {destination}...'.format(**f_args))
    else:
        print_info('Retrieving {source}...'.format(**f_args))

    if make_dir:
        os.makedirs(make_dir, exist_ok=True)

    urllib.request.urlretrieve(source, destination, _retrieve_report_hook)
    print('\r{source} saved to {destination}'.format(**f_args), end='')

    if chmod is not None:
        os.chmod(destination, chmod)
        print(' with mode {chmod:o}'.format(**f_args))
    else:
        print()

    return destination


def _retrieve_report_hook(num_blocks, block_size, total_size):
    ratio = num_blocks * block_size / total_size
    print('\r{ratio:.0%}'.format(ratio=ratio), end='')
