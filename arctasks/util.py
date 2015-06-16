import subprocess
import sys


def abort(code=0, message='Aborted'):
    if message:
        if code != 0:
            print(message, file=sys.stderr)
        else:
            print(message)
    sys.exit(code)


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


def confirm(ctx, prompt='Really?'):
    prompt = prompt.format(**ctx)
    prompt = '{prompt} [y/N] '.format(prompt=prompt)
    answer = input(prompt)
    answer = answer.strip().lower()
    return answer in ('y', 'yes')


def get_git_hash(short=True):
    args = ['git', 'rev-parse']
    if short:
        args.append('--short')
    args.append('HEAD')
    return subprocess.check_output(args).decode().strip()
