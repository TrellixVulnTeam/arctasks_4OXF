import subprocess

from arctasks.util import print_error, print_warning
from .util import abort, confirm


def git(args, return_output=False, **subprocess_args):
    if isinstance(args, str):
        args = args.split()
    git_args = ['git']
    git_args.extend(args)
    if return_output:
        output = subprocess.check_output(git_args, **subprocess_args)
        output = output.decode('utf-8').strip()
        return output
    else:
        return subprocess.check_call(git_args, **subprocess_args)


def commit_files(files, message=None, add=True):
    """Commit files with message.

    Args:
        files (list): The files to commit
        message: The default commit message
        add: Whether to add the files; if this is False, it will be
            assumed that the files were added manually before calling
            this function

    """
    f = locals()
    if add:
        git(['add'] + files)
    output = git(['diff', '--cached', '--color=always'], return_output=True)
    output = output.strip()
    if not output:
        abort(1, 'Nothing to commit')
    print(output)
    if not confirm({}, 'Commit this?'):
        abort(message='Commit aborted')
    prompt = 'Commit message '
    if message:
        default_message = message
        prompt = '{prompt} ["{message}"] '.format_map(locals())
        message = input(prompt)
        message = message.strip() or default_message
    else:
        message = ''
        while not message.strip():
            message = input(prompt)
    git(['commit', '-m', message] + files)


def current_branch():
    return git(['symbolic-ref', '--short', 'HEAD'], return_output=True)


def tag(tag_name, commit, annotate=True, message=None):
    if annotate and not message:
        abort(1, 'Annotated tag requires message')
    args = ['tag']
    if annotate:
        args.extend(['-a', '-m', message])
    args.append(tag_name)
    if commit:
        args.append(commit)
    git(args)


def version(short=True):
    """Get tag associated with HEAD; fall back to SHA1."""
    try:
        value = git(['rev-parse', 'HEAD'], return_output=True)
    except subprocess.CalledProcessError:
        print_error('`git rev-parse` failed, probably because this is not a git repo.')
        print_error('You can work around this by adding `version` to your task config.')
        abort(1)
    try:
        value = git(['describe', '--tags', value], return_output=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print_warning('Could not find tag for HEAD; falling back to SHA1')
        if short:
            value = value[:7]
    return value
