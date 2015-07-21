import configparser
import getpass
import json
import os
from collections import Mapping, OrderedDict, Sequence

from .arctask import arctask
from .util import abort, abs_path, asset_path, as_list, get_git_hash, print_error


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

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __contains__(self, key):
        obj = self
        path = key.split('.')
        for segment in path:
            if not super(Config, obj).__contains__(segment):
                return False
            obj = super(Config, obj).__getitem__(segment)
        return True


@arctask
def configure(ctx, env, file_name=None, options=None):
    """Configure the environment tasks are run in.

    Configuration can come from several places, listed here in order of
    increasing precedence:

        - Dynamically set defaults such as the current working directory
          and user.
        - Defaults defined in arctasks:tasks.cfg.
        - The config file specified by --file-name or tasks.cfg in the
          directory containing this module if --file-name isn't given.
        - Command line options passed as ``--options pants=cool,x=1``.
          These values will be parsed as JSON if possible. It's usually
          better to put options in a config file and only use --options
          for one-off runs.

    """
    cwd = os.getcwd()

    config = Config((
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
        config[k] = v

    # Extend/override from command line.
    # XXX: I don't particularly care for this bit of custom parsing, but
    # I also don't want to add a billion args to this task, and Invoke
    # doesn't currently parse dict-style options (although it may in the
    # future).
    if isinstance(options, str):
        options = as_list(options)
        for item in options:
            k, v = as_list(item, sep='=')
            try:
                v = json.loads(v)
            except ValueError:
                pass  # Assume value is str
            config[k] = v
    elif isinstance(options, Mapping):
        config.update(options)

    def interpolate(d):
        for k in d:
            v = d[k]
            if isinstance(v, str):
                d[k] = v.format(**config)
            elif isinstance(v, Config):
                interpolate(v)
            elif isinstance(v, Sequence):
                d[k] = v.__class__(item.format(**config) for item in v if isinstance(item, str))

    interpolate(config)

    config.move_to_end('remote')
    config.move_to_end('arctasks')
    if 'tasks' in config:
        config.move_to_end('tasks')

    ctx.update(config)
    ctx['__configured__'] = True
    ctx['__config__'] = config

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
def show_config(ctx, item=None, tasks=True, initial_level=0):
    """Show config; pass --item=<item> to show just one config item."""
    config = ctx['__config__']

    if item is not None:
        try:
            value = config[item]
        except KeyError:
            print_error('Unknown config item: {}'.format(item))
        else:
            print(item, '=', value)
    else:
        def as_string(c, skip, level):
            out = []
            indent = ' ' * (level * 4)
            max_key_len = len(max(list(c.keys()), key=len))
            for k, v in c.items():
                if k.startswith('_') or k in skip:
                    continue
                if isinstance(v, Config):
                    out.append('{indent}{k} =>'.format(**locals()))
                    out.append(as_string(v, skip, level + 1))
                else:
                    out.append('{indent}{k} = {v}'.format(**locals()))
            return '\n'.join(out)
        print(as_string(config, () if tasks else ('arctasks', 'tasks'), initial_level))
