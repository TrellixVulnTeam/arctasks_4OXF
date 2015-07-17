import configparser
import getpass
import json
import os
from collections import Mapping, OrderedDict

from .arctask import arctask
from .util import abort, abs_path, asset_path, as_list, get_git_hash


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

    def __contains__(self, key):
        obj = self
        path = key.split('.')
        for segment in path:
            if not super(Config, obj).__contains__(segment):
                return False
            obj = super(Config, obj).__getitem__(segment)
        return True

    def __str__(self):
        out = []
        for k, v in self.items():
            if isinstance(v, self.__class__):
                pass
            else:
                pass
        return '\n'.join(out)


@arctask
def configure(ctx, env, file_name=None, config=None):
    """Configure the environment tasks are run in.

    Configuration can come from several places, listed here in order of
    increasing precedence:

        - Dynamically set defaults such as the current working directory
          and user.
        - Defaults defined in arctasks:tasks.cfg.
        - The config file specified by --file-name or tasks.cfg in the
          directory containing this module if --file-name isn't given.
        - Command line options specified as ``--config pants=cool,x=1``.
          These values will be parsed as JSON if possible. It's usually
          better to put options in a config file and only use --config
          for one-off runs.

    """
    cwd = os.getcwd()

    all_config = Config((
        ('env', env),
        ('version', get_git_hash()),
        ('current_user', getpass.getuser()),
        ('cwd', cwd),
    ))

    # Mix in static defaults
    parser = configparser.ConfigParser()
    with open(asset_path('arctasks:tasks.cfg')) as config_fp:
        parser.read_file(config_fp)

    # Extend from project config file, if there is one
    if file_name is None:
        parser.read(os.path.join(cwd, 'tasks.cfg'))
    else:
        original_file_name = file_name
        file_name = abs_path(file_name)
        if not os.path.exists(file_name):
            abort(1, 'Config file "{}" not found'.format(original_file_name))
        with open(file_name) as config_fp:
            parser.read_file(config_fp)

    section = env if parser.has_section(env) else 'DEFAULT'
    for k, v in parser[section].items():
        v = json.loads(v)
        all_config[k] = v

    # Extend/override from command line.
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

    if not os.path.exists(all_config['local_settings_file']):
        all_config['local_settings_file'] = 'local.cfg'

    def interpolate(config):
        for k in config:
            v = config[k]
            if isinstance(v, str):
                config[k] = v.format(**all_config)
            elif isinstance(v, Config):
                interpolate(v)

    interpolate(all_config)
    all_config.move_to_end('remote')
    all_config.move_to_end('arctasks')
    ctx.update(all_config)
    ctx['__configured__'] = True
    ctx['__config__'] = all_config

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', ctx.django_settings_module)
    os.environ.setdefault('LOCAL_SETTINGS_FILE', ctx.local_settings_file)
    os.environ.setdefault('LOCAL_SETTINGS_CONFIG_QUIET', 'true')


def make_env_task(env_name):
    def func(ctx, file_name=None, config=None):
        configure(ctx, env_name, file_name, config)
    func.__name__ = env_name
    func.__doc__ = 'Configure for {env_name} environment'.format(**locals())
    return arctask(func)


# These let us do `inv dev ...` instead of `inv config dev ...`
dev = make_env_task('dev')
test = make_env_task('test')
stage = make_env_task('stage')
prod = make_env_task('prod')


@arctask(configured='dev')
def show_config(ctx, tasks=True, initial_level=0):
    def show(config, skip=(), level=initial_level):
        indent = ' ' * (level * 4)
        longest = len(max(config, key=len))
        for k, v in config.items():
            if k.startswith('_') or k in skip:
                continue
            display_value = ' = {}'.format(v) if not isinstance(v, Config) else ''
            print(
                '{indent}{k:<{longest}}{display_value}'
                    .format(indent=indent, k=k, longest=longest, display_value=display_value))
            if isinstance(v, Config):
                show(v, level=level + 1)
    skip = () if tasks else ('arctasks',)
    show(ctx['__config__'], skip=skip)
