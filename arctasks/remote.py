import os
import string
import tempfile

from runcommands import command
from runcommands.commands import local, remote
from runcommands.util import abs_path, args_to_str

from .util import as_tuple


@command
def manage(config, args):
    """Run a Django management command on the remote host."""
    remote(config, (
        'LOCAL_SETTINGS_FILE="{remote.build.local_settings_file}"',
        '{remote.build.python}',
        '{remote.build.manage}',
        args,
    ))


_rsync_default_mode = 'ug=rwX,o-rwx'


@command
def rsync(config, local_path, remote_path, user=None, host=None, sudo=False, run_as=None,
          dry_run=False, delete=False, excludes=(), default_excludes=True,
          echo=True, hide=None, mode=_rsync_default_mode, source='local'):
    """Copy files using rsync.

    By default, this pushes from ``local_path`` to ``remote_path``. To
    invert this--to pull from the remote to the local path--, pass
    ``source='remote'``.

    """
    remote_path = '{user}@{host}:{remote_path}'.format_map(locals())

    if source == 'local':
        source_path, destination_path = local_path, remote_path
    elif source == 'remote':
        source_path, destination_path = remote_path, local_path
    else:
        raise ValueError('source must be either "local" or "remote"')

    if sudo:
        rsync_path = '--rsync-path "sudo rsync"'
    elif run_as and run_as != user:
        run_as = args_to_str(run_as, format_kwargs=config)
        rsync_path = '--rsync-path "sudo -u {run_as} rsync"'.format_map(locals())
    else:
        rsync_path = None

    if default_excludes:
        default_excludes_file = abs_path('arctasks:rsync.excludes')
        exclude_from = ('--exclude-from', default_excludes_file)
    else:
        exclude_from = None

    excludes = as_tuple(excludes)
    if excludes:
        excludes = tuple("--exclude '{p}'".format(p=p) for p in excludes)

    local(config, (
        'rsync',
        '-rltvz',
        '--dry-run' if dry_run else '',
        '--delete' if delete else '',
        rsync_path,
        '--no-perms', '--no-group', '--chmod=%s' % mode,
        exclude_from,
        excludes,
        source_path, destination_path,
    ), echo=echo, hide=hide)


@command
def copy_file(config, local_path, remote_path, user=None, host=None, sudo=False, run_as=None,
              template=False, template_type=None, mode=_rsync_default_mode):
    local_path = abs_path(local_path, format_kwargs=config)
    rsync_args = dict(user=user, host=host, sudo=sudo, run_as=run_as, mode=mode)

    if template:
        with open(local_path) as in_fp:
            contents = in_fp.read()

        if template_type in (None, 'format'):
            contents = contents.format_map(config)
        elif template_type == 'string':
            template = string.Template(contents)
            contents = template.substitute(config)
        else:
            raise ValueError('Unrecognized template type: %s' % template_type)

        prefix = '%s-' % config.package
        suffix = '-%s' % os.path.basename(local_path)
        temp_fd, temp_path = tempfile.mkstemp(prefix=prefix, suffix=suffix, text=True)

        with os.fdopen(temp_fd, 'w') as temp_file:
            temp_file.write(contents)

        rsync(config, temp_path, remote_path, **rsync_args)
        os.remove(temp_path)
    else:
        rsync(config, local_path, remote_path, **rsync_args)
