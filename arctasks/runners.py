from invoke.exceptions import Failure

from .arctask import arctask
from .util import abort, abs_path, args_to_str, get_path


@arctask(configured='dev')
def local(ctx, args, cd=None, sudo=False, run_as=None, echo=None, hide=None,
          abort_on_failure=True, inject_context=True):
    """Run a command locally using ``ctx.run()``.

    If ``args`` contains format strings like "{xyz}", those will be
    filled from ``ctx``.

    When a local command fails, the default behavior is to exit with an
    error code.

    """
    path = 'PATH={path}'.format(path=get_path(ctx))
    args = (path, args)
    if sudo and run_as:
        abort(1, 'Only one of --sudo or --run-as may be passed')
    if sudo:
        args = ('sudo', args)
    elif run_as:
        args = ('sudo', '-u', run_as, args)
    if cd:
        cd = _get_cd_prefix(ctx, cd)
        args = (cd, args)
    cmd = args_to_str(args, format_kwargs=(ctx if inject_context else None))
    if echo is None:
        echo = ctx['run'].echo
    try:
        return ctx.run(cmd, echo=echo, hide=hide)
    except Failure as f:
        result = f.result
        if abort_on_failure:
            abort(1, 'Local command failed with exit code {0.exited}'.format(result))
        else:
            return result


@arctask(configured='dev')
def remote(ctx, args, user='{remote.user}', host='{remote.host}', path='{remote.extra_path}',
           cd='/tmp', sudo=False, run_as='{remote.run_as}', echo=None, hide=None,
           abort_on_failure=True, inject_context=True):
    """Run a command on the remote host using ssh.

    ``args`` can be a string or a list of strings that will be joined
    with " " into a single command string.

    ``user`` is the user to log in as. ``host`` is the host that will be
    logged in to. Commands will be run as ``user`` unless ``sudo`` or
    ``run_as`` is specified.

    ``path`` will be *appended* to the remote $PATH before running the
    command. It can be a string or a list of strings that will be joined
    with ":".

    TODO: Make it possible to *prepend* to the remote $PATH?

    The directory specified by ``cd`` will be changed into on the remote
    host before the command is run. By default, the remote working directory
    will be the home directory of ``user``.

    If ``sudo`` is specified, commands will be run on the remote host as
    ``sudo COMMAND``. If ``run_as`` is specified, commands will be run on
    the remote host as ``sudo -u USER COMMAND``.

    ``echo`` and ``hide`` are passed to ``ctx.run()``.

    """
    user = args_to_str(user, format_kwargs=ctx)
    host = args_to_str(host, format_kwargs=ctx)

    if sudo:
        run_as = 'sudo'
    elif run_as:
        run_as = args_to_str(run_as, format_kwargs=ctx)
        run_as = 'sudo -u {run_as}'.format(run_as=run_as)

    if cd:
        cd = _get_cd_prefix(ctx, cd)

    if path:
        path = args_to_str(path, format_kwargs=ctx)
        path = 'export PATH="${{PATH}}:{path}" &&'.format(path=path)

    cmd = args_to_str(args, format_kwargs=(ctx if inject_context else None))
    cmd = args_to_str((cd, path, cmd))
    cmd = "bash <<'EOBASH'\n        {cmd}\nEOBASH".format(cmd=cmd)
    cmd = args_to_str((run_as, cmd))
    cmd = "ssh -T {user}@{host} <<'EOSSH'\n    {cmd}\nEOSSH".format(**locals())

    if echo is None:
        echo = ctx['run'].echo
    try:
        return ctx.run(cmd, echo=echo, hide=hide)
    except Failure as f:
        result = f.result
        if abort_on_failure:
            abort(1, 'Remote command failed with exit code {0.exited}'.format(result))
        else:
            return result


def _get_cd_prefix(ctx, path):
    """Convert ``path`` to abs. path; return ``cd {path} &&``.

    See :func:`abs_path` for details on how ``path`` is converted to an
    absolute path.

    """
    path = args_to_str(path, format_kwargs=ctx)
    path = abs_path(path)
    return 'cd {path} &&'.format_map(locals())
