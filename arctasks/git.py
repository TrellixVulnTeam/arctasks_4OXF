import subprocess

from arctasks.util import print_error, print_warning
from .util import abort, confirm


def run(args, return_output=False, **subprocess_args):
    # Make sure we're in a git work tree.
    # TODO: Be even more strict and require $PWD/.git?
    try:
        subprocess.check_call(
            ['git', 'rev-parse', '--is-inside-work-tree'], stdout=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        abort(1, 'Cannot run git commands outside of a git repository.')

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
        run(['add'] + files)
    output = run(['diff', '--cached', '--color=always'], return_output=True)
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
    run(['commit', '-m', message] + files)


def current_branch():
    return run(['rev-parse', '--abbrev-ref', 'HEAD'], return_output=True)


def tag(tag_name, commit, annotate=True, message=None):
    if annotate and not message:
        abort(1, 'Annotated tag requires message')
    args = ['tag']
    if annotate:
        args.extend(['-a', '-m', message])
    args.append(tag_name)
    if commit:
        args.append(commit)
    run(args)


def version(short=True):
    """Get tag associated with HEAD; fall back to SHA1.

    If HEAD is tagged, return the tag name; otherwise fall back to
    HEAD's SHA1, shortened by default.

    .. note:: Only annotated tags are considered.

    TODO: Support non-annotated tags?

    Args:
        short: When falling back to SHA1, this indicates whether to
            return the shortened unique SHA1 (typically 7 characters but
            not always)

    """
    try:
        value = run(['describe', '--exact-match'], return_output=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print_warning('HEAD is not tagged; falling back to SHA1')
        value = run(['rev-parse', '--short' if short else '', 'HEAD'], return_output=True)
    return value
