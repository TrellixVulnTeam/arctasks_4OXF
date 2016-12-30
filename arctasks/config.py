import getpass
import json
import os
import tempfile
from collections import Mapping, OrderedDict, Sequence
from configparser import ConfigParser, ExtendedInterpolation

from . import git
from .arctask import arctask
from .util import abort, abs_path, asset_path, as_list, print_error


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


class LazyConfigValue:

    def __init__(self, callable_, args=(), kwargs={}):
        self.callable = callable_
        self.args = args
        self.kwargs = kwargs

    def __call__(self):
        return self.callable(*self.args, **self.kwargs)


@arctask
def configure(ctx, env, version=None, file_name=None, options=None):
    """Configure the environment tasks are run in.

    Configuration can come from several places, listed here in order of
    increasing precedence:

        - Dynamically set defaults such as the current working directory
          and user.
        - Defaults defined in arctasks:tasks.cfg.
        - The config file specified by --file-name or tasks.cfg in the
          current directory if --file-name isn't specified.
        - Command line options passed as ``--options pants=cool,x=1``.
          These values will be parsed as JSON if possible. It's usually
          better to put options in a config file and only use --options
          for one-off runs.

    .. note:: If this task is called multiple times, the ``file_name``
       passed to the first call will be used for subsequent calls if
       ``file_name`` isn't passed to those subsequent calls.

    """
    file_name = file_name or ctx.get('__config_file_name__')

    cwd = os.getcwd()

    config = Config((
        ('env', env),
        ('version', version if version is not None else LazyConfigValue(git.version)),
        ('current_user', LazyConfigValue(getpass.getuser)),
        ('cwd', cwd),
        ('arctasks.static.collectstatic.static_root', LazyConfigValue(tempfile.mkdtemp)),
    ))

    parser = ConfigParser(interpolation=ExtendedInterpolation())

    def read_config_from_file(name, check_exists=True):
        # Read config file and add items from section to config.
        if not os.path.isfile(name):
            if check_exists:
                abort(1, 'Config file "{name}" not found'.format(name=name))
            return
        with open(name) as config_fp:
            parser.read_file(config_fp)
        section = env if parser.has_section(env) else 'DEFAULT'
        for k, v in parser[section].items():
            v = json.loads(v)
            config[k] = v

    def start_interpolation():
        interpolated = []
        interpolate(config, interpolated)
        while interpolated:
            interpolated = []
            interpolate(config, interpolated)

    def interpolate(obj, interpolated):
        if isinstance(obj, LazyConfigValue):
            obj = obj()
        if isinstance(obj, str):
            new_value = obj.format(**config)
            if new_value != obj:
                obj = new_value
                interpolated.append(obj)
        elif isinstance(obj, Mapping):
            for key in obj:
                obj[key] = interpolate(obj[key], interpolated)
        elif isinstance(obj, Sequence):
            obj = obj.__class__(interpolate(thing, interpolated) for thing in obj)
        return obj

    # Mix in static defaults
    read_config_from_file(asset_path('arctasks:tasks.cfg'))

    # Extend from project config file, if there is one
    if file_name is None:
        file_name = os.path.join(cwd, 'tasks.cfg')
        read_config_from_file(file_name, check_exists=False)
    else:
        file_name = abs_path(file_name)
        read_config_from_file(file_name)

    if options:
        # Extend/override from command line.
        # XXX: I don't particularly care for this bit of custom parsing, but
        # I also don't want to add a billion args to this task, and Invoke
        # doesn't currently parse dict-style options (although it may in the
        # future).
        if isinstance(options, str):
            # First, convert 'a=1,b=2' to ['a=1', 'b=2'].
            options = as_list(options)
            # Then, convert ['a=1', 'b=2'] to {'a': 1, 'b': 2}.
            options = dict(as_list(option, sep='=') for option in options)
            # Finally, convert values from JSON.
            for opt, val in options.items():
                try:
                    options[opt] = json.loads(val)
                except ValueError:
                    pass  # Assume value is str
        config.update(options)

    start_interpolation()

    config.move_to_end('remote')
    config.move_to_end('arctasks')
    if 'tasks' in config:
        config.move_to_end('tasks')

    ctx.update(config)
    ctx['__configured__'] = True
    ctx['__config__'] = config
    ctx['__config_file_name__'] = file_name

    os.environ['DJANGO_SETTINGS_MODULE'] = ctx.django_settings_module
    os.environ['LOCAL_SETTINGS_FILE'] = ctx.local_settings_file
    os.environ['LOCAL_SETTINGS_CONFIG_QUIET'] = 'true'


def make_env_task(env_name):
    def func(ctx, version=None, file_name=None, options=None):
        configure(ctx, env_name, version, file_name, options)
    func.__name__ = env_name
    func.__doc__ = 'Configure for {env_name} environment'.format(**locals())
    return arctask(func)


# These let us do `inv dev ...` instead of `inv config dev ...`
dev = make_env_task('dev')
docker = make_env_task('docker')
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
