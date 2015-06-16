from invoke.exceptions import Failure
from invoke.tasks import ctask as task

from .config import configured
from .util import abort, args_to_str


@task(configured)
def local(ctx, args, cd=None, sudo=False, run_as=None, echo=True, hide=False,
          abort_on_failure=True):
    """Run a command locally using ``ctx.run()``.

    If ``args`` contains format strings like "{xyz}", those will be
    filled from ``ctx``.

    When a local command fails, the default behavior is to exit with an
    error code.

    """
    if sudo and run_as:
        abort(1, 'Only one of --sudo or --run-as may be passed')
    if sudo:
        args = ('sudo', args)
    elif run_as:
        args = ('sudo', '-u', run_as, args)
    if cd:
        args = (('cd', cd, '&&'), args)
    cmd = args_to_str(args, format_kwargs=ctx)
    try:
        return ctx.run(cmd, echo=echo, hide=hide)
    except Failure as f:
        result = f.result
        if abort_on_failure:
            abort(1, 'Local command failed with exit code {0.exited}'.format(result))
        else:
            return result


@task(configured)
def remote(ctx, args, user=None, host=None, cd=None, path=None, echo=True, hide=False,
           abort_on_failure=True):
    """Run a command on the remote host using ssh.

    ``args`` can be a string or a list of strings that will be joined
    with " " into a single string.

    The directory specified by ``cd`` is changed into on the remote host
    before the command is run.

    ``path`` will be *appended* to the remote $PATH before running the
    command. It can be a string or a list of strings that will be joined
    with ":".

    ``echo`` and ``hide`` are passed to ``ctx.run()``.

    """
    cmd = []
    user = user if user is not None else ctx.task.remote.user
    host = host if host is not None else ctx.task.remote.host

    if path is not None:
        path = args_to_str(path, joiner=':')
        path = 'export PATH="$PATH:{path}" &&'.format(path=path)
        cmd.append(path)

    if cd:
        cd = cd.format(**ctx)
        cd = 'cd {cd} &&'.format(cd=cd)
        cmd.append(cd)

    args = args_to_str(args, format_kwargs=ctx)
    cmd.append(args)

    cmd = ' '.join(cmd)
    cmd = "'{cmd}'".format(cmd=cmd)

    ssh = 'ssh {user}@{host}'.format(user=user, host=host)
    cmd = [ssh, cmd]
    cmd = ' '.join(cmd)

    return local(ctx, cmd, echo=echo, hide=hide, abort_on_failure=abort_on_failure)
