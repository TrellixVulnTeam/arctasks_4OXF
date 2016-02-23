from invoke.exceptions import Failure

from .arctask import arctask
from .util import abort, args_to_str


@arctask(configured='dev')
def local(ctx, args, cd=None, sudo=False, run_as=None, echo=None, hide=None,
          abort_on_failure=True, inject_context=True):
    """Run a command locally using ``ctx.run()``.

    If ``args`` contains format strings like "{xyz}", those will be
    filled from ``ctx``.

    When a local command fails, the default behavior is to exit with an
    error code.

    """
    path = 'PATH={bin.dir}:{cwd}/node_modules/.bin:$PATH'.format(**ctx)
    args = (path, args)
    if sudo and run_as:
        abort(1, 'Only one of --sudo or --run-as may be passed')
    if sudo:
        args = ('sudo', args)
    elif run_as:
        args = ('sudo', '-u', run_as, args)
    if cd:
        args = (('cd', cd, '&&'), args)
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
           cd=None, sudo=False, run_as='{remote.run_as}', echo=None, hide=None,
           abort_on_failure=True, inject_context=True, many=False):
    """Run a command on the remote host using ssh.

    ``args`` can be a string or a list of strings that will be joined
    with " " into a single command string.

    .. note:: If ``args`` is something like ``"abc && xyz"``, only the
              ``abc`` command will be run as the user indicated by ``sudo``
              or ``run_as``. To get around this, instead pass ``args`` as
              ``("abc", "xyz")`` with ``many=True`` or ``many='&&'`` or
              ``many='||'``.

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

    If ``many`` is specified, ``args`` must be a list of commands. Each item
    can be a string or a list of strings that will be joined with " " (just
    like when running a single command). The list of commands will be joined
    with the string indicated by ``many`` ("&&" will be used if ``many`` is
    ``True``). All the commands will be run as the same user (as indicated
    by ``sudo`` or ``run_as``) in the same directory using the same $PATH.

    .. note:: ``many`` is kind of a hack for cases where you want to run
              commands on the remote host as a certain user but can't log
              in as that user (as is the case currently with service users).

    """
    cmd = []

    if path:
        path = args_to_str(('$PATH', path), joiner=':')
        path = 'PATH="{path}"'.format(path=path)
    else:
        path = ''

    if cd:
        cmd.extend(('cd', cd, '&&'))

    run_as = args_to_str(run_as, format_kwargs=ctx)

    if sudo:
        run_as = 'sudo'
    elif run_as:
        run_as = 'sudo -u {run_as}'.format(run_as=run_as)
    else:
        run_as = ''

    if many:
        if not isinstance(args, (list, tuple)):
            raise TypeError('args must be a list or tuple when --many')
        if many is True:
            many = '&&'
        if many not in ('&&', '||', '|'):
            raise ValueError('many must be one of True, "&&", "||", "|", or ";"')
    else:
        args = [args]

    for a in args[:-1]:
        cmd.extend((run_as, path, a, many))
    cmd.extend((run_as, path, args[-1]))

    cmd = args_to_str(cmd, format_kwargs=(ctx if inject_context else None))
    cmd = "'{cmd}'".format(cmd=cmd)
    cmd = ('ssh', '{user}@{host}'.format(**locals()), cmd)

    return local(
        ctx, cmd, echo=echo, hide=hide, abort_on_failure=abort_on_failure,
        inject_context=inject_context)
