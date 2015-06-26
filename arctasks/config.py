import configparser
import getpass
import json
import os
import pkg_resources
from collections import Mapping, OrderedDict

from invoke import ctask as task

from .util import abort, as_list, get_git_hash, print_warning


DEFAULT_CONFIG = (
    # Meta
    ('_arctasks.dir', pkg_resources.resource_filename('arctasks', '')),
    ('_invoke.version', '0.10.1'),
    ('cwd', os.getcwd()),
    ('distribution', '{package}'),
    ('version', get_git_hash()),

    # Local
    ('venv', '.env'),
    ('bin', '{venv}/bin'),
    ('python', '{bin}/python'),
    ('pip', '{bin}/pip'),
    ('requirements', 'requirements.txt'),

    # Local paths
    ('path.build.root', '{cwd}/build/{version}'),
    ('path.build.dist', '{path.build.root}/dist'),

    # Django
    ('django_settings_module', '{package}.settings'),
    ('local_settings_file', 'local.{env}.cfg'),

    # Database
    ('db.type', 'postgresql'),
    ('db.name', '{package}'),

    ## Remote paths

    # Project root directory
    ('remote.path.root', '/vol/www/{package}'),
    # Pointer to active build for env (stage, prod)
    ('remote.path.env', '{remote.path.root}/{env}'),
    # Media and static directories for env
    ('remote.path.media', '/vol/www/{package}/media/{env}'),
    ('remote.path.static', '/vol/www/{package}/static/{env}'),

    # Build root for env; contains all the builds for an env
    ('remote.build.root', '{remote.path.root}/builds/{env}'),
    # Where the current build will be built and what remote.path.env will end up pointing at
    ('remote.build.dir', '{remote.build.root}/{version}'),
    # Virtualenv for build
    ('remote.build.venv', '{remote.build.dir}/.env'),
    ('remote.build.bin', '{remote.build.venv}/bin'),
    ('remote.build.pip', '{remote.build.bin}/pip'),
    ('remote.build.python', '{remote.build.bin}/python'),
    # Source distributions for build
    ('remote.build.dist', '{remote.build.dir}/dist'),
    ('remote.build.manage_template', '{_arctasks.dir}/templates/manage.py.template'),
    ('remote.build.manage', '{remote.build.dir}/manage.py'),
    ('remote.build.wsgi', '{remote.build.dir}/wsgi'),

    # Pip root directory for env
    ('remote.pip.root', '{remote.path.root}/pip/{env}'),
    # Shared pip cache for env
    ('remote.pip.download_cache', '{remote.pip.root}/download-cache'),
    # Shared pip wheel dir for env
    ('remote.pip.wheel_dir', '{remote.pip.root}/wheelhouse'),
    # ARC's local package index
    ('remote.pip.find_links', 'file:///vol/www/cdn/pypi/dist'),

    ## Default task config

    ('task.remote.user', getpass.getuser()),
    ('task.remote.host', 'hrimfaxi.oit.pdx.edu'),

    ('task.provision.pip.version', '7.0.3'),

    ('task.rsync.default_excludes', (
        '__pycache__/',
        '.DS_Store',
        '*.pyc',
        '*.swp',
    )),

    # Copied from Bootstrap (from grunt/configBridge.json in the source)
    ('task.lessc.autoprefix.browsers', ','.join((
        'Android 2.3',
        'Android >= 4',
        'Chrome >= 20',
        'Firefox >= 24',
        'Explorer >= 8',
        'iOS >= 6',
        'Opera >= 12',
        'Safari >= 6',
    ))),
)


DEFAULT_CONFIG_FILE = os.path.join(os.getcwd(), 'tasks.cfg')


class Config(OrderedDict):

    def __getitem__(self, key):
        obj = self
        keys = key.split('.')
        for k in keys[:-1]:
            obj = super(Config, obj).__getitem__(k)
        return super(Config, obj).__getitem__(keys[-1])

    def __setitem__(self, key, value):
        obj = self
        keys = key.split('.')
        for k in keys[:-1]:
            obj = super(Config, obj).setdefault(k, Config())
        super(Config, obj).__setitem__(keys[-1], value)

    def __getattribute__(self, key):
        try:
            return super().__getattribute__(key)
        except AttributeError as attribute_error:
            try:
                return self[key]
            except KeyError:
                raise attribute_error

    def __str__(self):
        out = []
        for k, v in self.items():
            if isinstance(v, self.__class__):
                pass
            else:
                pass
        return '\n'.join(out)


@task
def configure(ctx, env, file_name=None, config=None):
    """Configure the environment tasks are run in.

    Configuration can come from three places, listed here in order of
    increasing precedence:

        - Defaults defined in this module in :global:`.DEFAULT_CONFIG`.
        - The config file specified by --file-name or tasks.cfg in the
          directory containing this module if --file-name isn't given.
        - Command line options specified as ``--config pants=cool,x=1``.
          These values will be parsed as JSON if possible. It's usually
          better to put options in a config file and only use --config
          for one-off runs.

    """
    all_config = Config()

    if file_name is None and os.path.exists(DEFAULT_CONFIG_FILE):
        file_name = DEFAULT_CONFIG_FILE

    if file_name is not None:
        if not os.path.exists(file_name):
            abort(1, 'Config file "{}" not found'.format(file_name))
        parser = configparser.ConfigParser()
        with open(file_name) as config_fp:
            parser.read_file(config_fp)
        section = env if parser.has_section('env') else 'DEFAULT'
        for k, v in parser[section].items():
            v = json.loads(v)
            all_config[k] = v

    # XXX: I don't particularly care for this bit of custom parsing, but
    # I also don't want to add a billion args to this task, and Invoke
    # doesn't currently parse dict-style options (although it may in the
    # future).
    if isinstance(config, str):
        config = as_list(config)
        for item in config:
            k, v = as_list(item, sep='=')
            try:
                v = json.loads(v)
            except ValueError:
                pass  # Assume value is str
            all_config[k] = v
    elif isinstance(config, Mapping):
        all_config.update(config)

    all_config.setdefault('env', env)
    for k, v in DEFAULT_CONFIG:
        all_config.setdefault(k, v)

    for k in all_config:
        v = all_config[k]
        if isinstance(v, str):
            all_config[k] = v.format(**all_config)

    def interpolate(config):
        for k in config:
            v = config[k]
            if isinstance(v, str):
                config[k] = v.format(**all_config)
            elif isinstance(v, Config):
                interpolate(v)

    interpolate(all_config)
    all_config.move_to_end('remote')
    all_config.move_to_end('task')
    ctx.update(all_config)
    ctx['__configured__'] = True
    ctx['__config__'] = all_config

    if not os.path.exists(ctx.local_settings_file):
        ctx.local_settings_file = 'local.cfg'
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', ctx.django_settings_module)
    os.environ.setdefault('LOCAL_SETTINGS_FILE', ctx.local_settings_file)
    os.environ.setdefault('LOCAL_SETTINGS_CONFIG_QUIET', 'true')


def make_env_task(env_name):
    def func(ctx, file_name=None, config=None):
        configure(ctx, env_name, file_name, config)
    func.__name__ = env_name
    func.__doc__ = 'Configure for {env_name} environment'.format(**locals())
    return task(func)


# These let us do `inv dev ...` instead of `inv config dev ...`
dev = make_env_task('dev')
test = make_env_task('test')
stage = make_env_task('stage')
prod = make_env_task('prod')


@task
def configured(ctx, default_env='dev'):
    if not ctx.get('__configured__'):
        configure(ctx, default_env)
        print_warning(
            'Configuring for {env} environment since no config task was specified'
            .format(env=default_env))


@task(configured)
def show_config(ctx, tasks=True, initial_level=0):
    def show(config, skip=(), level=initial_level):
        indent = ' ' * (level * 4)
        longest = len(max(config, key=len))
        for k, v in config.items():
            if k.startswith('_') or k in skip:
                continue
            display_value = ' = {}'.format(v) if isinstance(v, str) else ''
            print(
                '{indent}{k:<{longest}}{display_value}'
                    .format(indent=indent, k=k, longest=longest, display_value=display_value))
            if isinstance(v, Config):
                show(v, level=level + 1)
    skip = () if tasks else ('task',)
    show(ctx['__config__'], skip=skip)
