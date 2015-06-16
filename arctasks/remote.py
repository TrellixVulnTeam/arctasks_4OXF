import os
import tempfile

from invoke.tasks import ctask as task

from .config import configured
from .runners import local, remote
from .util import as_list


DEFAULT_MODE = 'ug=rwX,o-rwx'


@task(configured)
def manage(ctx, args):
    """Run a Django management command on the remote host."""
    remote(ctx, ('{remote.build.python}', '{remote.build.manage}', args), cd='{remote.build.dir}')


@task
def rsync(ctx, local_path, remote_path, dry_run=False, delete=False, exclude_patterns=(), echo=True,
          hide=True, mode=DEFAULT_MODE):
    exclude_patterns += tuple(as_list(ctx.task.rsync.default_excludes))
    local(ctx, (
        'rsync', '-rltvz',
        '--dry-run' if dry_run else '',
        '--delete' if delete else '',
        '--no-perms', '--no-group', '--chmod=%s' % mode,
        tuple("--exclude '{p}'".format(p=p) for p in exclude_patterns),
        local_path, '{task.remote.user}@{task.remote.host}:%s' % remote_path,
    ), echo=echo, hide=hide)


@task(configured)
def scp(ctx, local_path, remote_path, template=False, mode=DEFAULT_MODE):
    if template:
        local_path = local_path.format(**ctx)
        with open(local_path) as in_fp:
            contents = in_fp.read().format(**ctx)
        temp_fd, local_path = tempfile.mkstemp(
            prefix='%s-' % ctx.package,
            suffix='-%s' % os.path.basename(local_path),
            text=True)
        os.write(temp_fd, contents.encode('utf-8'))
        os.close(temp_fd)
    local(ctx, ('scp', local_path, '{task.remote.user}@{task.remote.host}:%s' % remote_path))
    remote(ctx, ('chmod', mode, remote_path))
