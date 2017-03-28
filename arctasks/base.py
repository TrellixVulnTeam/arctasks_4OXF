import glob
import os
import posixpath
import shutil
import site
import sys
import urllib.request

from runcommands import command
from runcommands.commands import local
from runcommands.util import abort, abs_path, as_list, printer


@command
def clean(config):
    local(config, 'find . -name __pycache__ -type d -print0 | xargs -0 rm -r')
    local(config, 'find . -name "*.py[co]" -print0 | xargs -0 rm')
    local(config, 'rm -rf build')
    local(config, 'rm -rf dist')


@command(default_env='dev')
def install(config, requirements='{pip.requirements}', upgrade=False, add_to_path=True):
    local(config, (
        '{bin.pip}', 'install', '--upgrade' if upgrade else '', '-r', requirements,
    ), echo=config._get_dotted('run.echo'))

    # Add (or re-add) virtualenv site-packages to sys.path
    if add_to_path:
        printer.info('Adding virtualenv site-packages to sys.path')
        paths = glob.glob(posixpath.join(config.venv, 'lib/python*/site-packages'))
        num_paths = len(paths)
        if num_paths == 0:
            abort(1, 'Could not find site-packages after install')
        elif num_paths == 1:
            printer.info('Found site-packages at', paths[0])
            site.addsitedir(paths[0])
        else:
            abort(1, 'Too many site-packages directories found after install')


@command(default_env='dev')
def virtualenv(config, where, executable=None, overwrite=False):
    create = True
    if os.path.exists(where):
        if overwrite:
            print('Overwriting virtualenv {where}'.format(where=where))
            shutil.rmtree(where)
        else:
            create = False
            print('virtualenv {where} exists'.format(where=where))
    if create:
        if executable is None:
            executable = 'python{v.major}.{v.minor}'.format(v=sys.version_info)
            printer.info('Automatically selected {executable} for virtualenv'.format_map(locals()))
        local(config, ('virtualenv', '-p', executable, where))
        local(config, '{bin.pip} install -U setuptools')
        local(config, '{bin.pip} install -U pip')


@command(default_env='dev')
def lint(config, where=None):
    """Check source files for issues.

    For Python code, this uses the flake8 package, which wraps pep8 and
    pyflakes. To configure flake8 for your project, add a setup.cfg file
    with a [flake8] section.

    TODO: Lint JS?
    TODO: Lint CSS?

    """
    if where is None:
        where = config['package']
        where = where.replace('.', '/')
    else:
        where = where.format_map(config)
    printer.header('Checking for Python lint in {where}...'.format(where=where))
    result = local(config, ('flake8', where), abort_on_failure=False)
    if result.failed:
        pieces_of_lint = len(result.stdout_lines)
        printer.error(pieces_of_lint, 'pieces of Python lint found')
    else:
        printer.success('Python is clean')


_npm_install_modules = (
    'autoprefixer',
    'bower',
    'jshint',
    'less',
    'less-plugin-autoprefix',
    'less-plugin-clean-css',
    'node-sass',
    'postcss-clean',
    'postcss-cli',
    'requirejs',
    'uglify-js',
)


@command(default_env='dev')
def npm_install(config, where='.', modules=_npm_install_modules, force=False, overwrite=False):
    """Install node modules via npm into ./node_modules.

    By default, any modules that are already installed will be skipped.
    Pass --force to install all specified modules.

    """
    result = local(config, 'which npm', echo=False, hide='stdout', abort_on_failure=False)
    if result.failed:
        abort(1, 'node and npm must be installed first')
    where = abs_path(where, format_kwargs=config)
    node_modules = os.path.join(where, 'node_modules')
    if overwrite and os.path.isdir(node_modules):
        printer.warning('Removing {node_modules}...'.format_map(locals()))
        shutil.rmtree(node_modules)
    modules = as_list(modules)
    local(config, ('npm install', ('--force' if force else ''), modules), cd=where)


@command
def retrieve(config, source, destination, overwrite=False, chmod=None):
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
    source = source.format(**config)
    destination = destination.format(**config)
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
            printer.warning(
                '{destination} exists; pass --overwrite to re-fetch it'.format(**f_args))
            return destination
        else:
            printer.warning('Overwriting {destination}...'.format(**f_args))
    else:
        printer.info('Retrieving {source}...'.format(**f_args))

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
