import os
import tempfile

from .arctask import arctask
from .runners import local, remote
from .util import as_tuple


@arctask(configured=True)
def manage(ctx, args):
    """Run a Django management command on the remote host."""
    remote(ctx, (
        'LOCAL_SETTINGS_FILE="{remote.build.local_settings_file}"',
        '{remote.build.python}',
        '{remote.build.manage}',
        args,
    ))


_rsync_default_mode = 'ug=rwX,o-rwx'
_rsync_default_excludes = ('__pycache__/', '.DS_Store', '*.pyc', '*.swp')


@arctask(configured=True, optional=('default_excludes',))
def rsync(ctx, local_path, remote_path, user='{remote.user}', host='{remote.host}',
          run_as='{remote.run_as}', dry_run=False, delete=False, excludes=(),
          default_excludes=_rsync_default_excludes, echo=True, hide=True, mode=_rsync_default_mode):
    excludes = as_tuple(excludes)
    if default_excludes:
        excludes += as_tuple(default_excludes)
    local(ctx, (
        'rsync',
        '-rltvz',
        '--dry-run' if dry_run else '',
        '--delete' if delete else '',
        '--rsync-path "sudo -u {run_as} rsync"'.format(run_as=run_as) if run_as else '',
        '--no-perms', '--no-group', '--chmod=%s' % mode,
        tuple("--exclude '{p}'".format(p=p) for p in excludes),
        local_path,
        '{user}@{host}:{remote_path}'.format(**locals()),
    ), echo=echo, hide=hide)


@arctask(configured=True)
def copy_file(ctx, local_path, remote_path, user='{remote.user}', host='{remote.host}',
              run_as='{remote.run_as}', template=False,
              mode=_rsync_default_mode):
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
    rsync(ctx, local_path, remote_path, user=user, host=host, run_as=run_as, mode=mode)
