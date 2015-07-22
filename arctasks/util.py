import enum
import importlib
import os
import subprocess
import sys
from functools import partial


def abort(code=0, message='Aborted', color=True):
    if message:
        if color:
            if color is True:
                color = 'error' if code else 'warning'
            message = colorize(message, color=color)
        if code != 0:
            print(message, file=sys.stderr)
        else:
            print(message)
    sys.exit(code)


def abs_path(path, format_kwargs={}):
    """Get abs. path for ``path``.

    ``path`` may be a relative or absolute file system path or an asset
    path. If ``path`` is already an abs. path, it will be returned as
    is. Otherwise, it will be converted into a normalized abs. path.

    """
    if format_kwargs:
        path = path.format(**format_kwargs)
    if not os.path.isabs(path):
        if ':' in path:
            path = asset_path(path)
        else:
            path = os.path.expanduser(path)
            path = os.path.normpath(os.path.abspath(path))
    return path


def asset_path(path, format_kwargs={}):
    """Get absolute path to asset in package.

    ``path`` can be just a package name like 'arctasks' or it can be
    a package name and a relative file system path like 'arctasks:util'.

    """
    if ':' in path:
        package_name, *rel_path = path.split(':', 1)
    else:
        package_name, rel_path = path, ()
    package = importlib.import_module(package_name)
    if not hasattr(package, '__file__'):
        raise ValueError("Can't compute path relative to namespace package")
    package_path = os.path.dirname(package.__file__)
    path = os.path.join(package_path, *rel_path)
    path = os.path.normpath(os.path.abspath(path))
    if format_kwargs:
        path = path.format(**format_kwargs)
    return path


def args_to_str(args, joiner=' ', format_kwargs={}):
    # If ``args`` is a list or tuple, it will first be joined into a string
    # using the join string specified by ``joiner``. Empty strings will be
    # removed.
    #
    # ``args`` may contain nested lists and tuples, which will be joined
    # recursively.
    #
    # After ``args`` has been joined into a single string, its leading and
    # trailing whitespace will be stripped and then ``format_args`` will be
    # injected into it using ``str.format(**format_kwargs)``.
    if not isinstance(args, str):
        if isinstance(args, (list, tuple)):
            args_to_join = (args_to_str(a, joiner, None) for a in args)
            args = joiner.join(a for a in args_to_join if a)
        else:
            raise TypeError('args must be a str, list, or tuple')
    args = args.strip()
    if format_kwargs:
        args = args.format(**format_kwargs)
    return args


def as_list(items, sep=','):
    if isinstance(items, str):
        items = items.strip().split(sep)
        items = [item.strip() for item in items]
    return items


def as_tuple(items, sep=','):
    return tuple(as_list(items, sep))


def confirm(ctx, prompt='Really?', color='warning', yes_values=('y', 'yes')):
    prompt = prompt.format(**ctx)
    prompt = '{prompt} [y/N] '.format(prompt=prompt)
    if isinstance(yes_values, str):
        yes_values = (yes_values,)
    if color is not None:
        prompt = colorize(prompt, color=color)
    try:
        answer = input(prompt)
    except KeyboardInterrupt:
        print()
        return False
    answer = answer.strip().lower()
    return answer in yes_values


def get_git_hash(short=True):
    args = ['git', 'rev-parse']
    if short:
        args.append('--short')
    args.append('HEAD')
    return subprocess.check_output(args).decode().strip()


class Color(enum.Enum):

    none = ''
    reset = '\033[0m'
    black = '\033[90m'
    red = '\033[91m'
    green = '\033[92m'
    yellow = '\033[93m'
    blue = '\033[94m'
    magenta = '\033[95m'
    cyan = '\033[96m'
    white = '\033[97m'

    def __str__(self):
        return self.value


COLOR_MAP = {
    'header': Color.magenta,
    'info': Color.blue,
    'success': Color.green,
    'warning': Color.yellow,
    'error': Color.red,
}


def colorize(*args, color=Color.none, sep=' ', end=Color.reset):
    if not isinstance(color, Color):
        if color in COLOR_MAP:
            color = COLOR_MAP[color]
        else:
            try:
                color = Color[color]
            except KeyError:
                raise ValueError('Unknown color: {color}'.format(color=color))
    args = (color,) + args
    string = []
    for arg in args[:-1]:
        string.append(str(arg))
        if not isinstance(arg, Color):
            string.append(sep)
    string.append(str(args[-1]))
    string = ''.join(string)
    if end:
        string = '{string}{end}'.format(**locals())
    return string


def print_color(*args, color=Color.none, file=sys.stdout, **kwargs):
        try:
            is_a_tty = file.isatty()
        except AttributeError:
            is_a_tty = False
        if is_a_tty:
            string = colorize(*args, color=color, **kwargs)
            print(string, **kwargs)
        else:
            args = [a for a in args if not isinstance(a, Color)]
            print(*args, **kwargs)


print_header = partial(print_color, color=COLOR_MAP['header'])
print_info = partial(print_color, color=COLOR_MAP['info'])
print_success = partial(print_color, color=COLOR_MAP['success'])
print_warning = partial(print_color, color=COLOR_MAP['warning'])
print_error = partial(print_color, color=COLOR_MAP['error'])
