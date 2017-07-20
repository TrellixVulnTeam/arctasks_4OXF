import json
import os
import posixpath
import shutil
import ssl
import string
import sys
import tarfile
import tempfile
from configparser import ConfigParser, ExtendedInterpolation
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import urlopen, urlretrieve

from runcommands import command
from runcommands.commands import show_config, local, remote
from runcommands.util import abort, confirm, load_object, printer

from . import django
from . import git
from .base import clean, install
from .remote import manage as remote_manage, rsync, copy_file
from .static import build_static, collectstatic
from .util import abs_path


class Deployer:

    """Default deployment strategy.

    This strategy deploys a mod_wsgi/Django project.

    It's assumed that the directory structure on the deployment host
    looks like this::

        /vol/www/{package}/
            {env}                 # Symlink pointing at active build in builds/{env}/
            builds/{env}/         # Builds for env (stage, prod)
                {version}/        # Current build root
                    .env/         # Virtualenv directory
                    wsgi/wsgi.py  # WSGI entry point [1]
                    media         # Symlink to media/{env} [2]
                    static        # Symlink to static/{env} [2]
            pip/cache/            # Cached package downloads
            pip/wheel/            # Cached package builds
            media/{env}/          # Media files for env (shared across builds)
            static/{env}/         # Static files for env (shared across builds)

    [1] Use {package}/wsgi.py for legacy builds.
    [2] Only necessary for legacy Apache config; only created when the
        ``--old-style`` flag is passed to the :func:`.link` command.

    """

    def __init__(self, config, **options):
        self.started = datetime.now()

        version = options['version']
        if version is not None:
            config = config.copy(version=version)

        self.options = self.init_options(config, options)
        self.config = config
        self.build_dir = config.path.build.root
        self.current_branch = git.current_branch()

        self.remote_build_root = config.remote.build.root
        self.remote_build_dir = config.remote.build.dir

        archive_directory = os.path.dirname(self.build_dir)
        archive_file_name = '{config.version}.tgz'.format_map(locals())
        self.archive_path = os.path.join(archive_directory, archive_file_name)

    def init_options(self, config, options):
        remove_distributions = list(options.get('remove_distributions') or ())
        options['remove_distributions'] = [config.distribution] + remove_distributions
        options['build_static'] = options['static'] and options['build_static']
        return options

    def run(self):
        """Deploy."""
        self.show_info()
        self.confirm()
        self.do_local_preprocessing()
        if self.options['push']:
            self.push()
        self.do_remote_commands()
        if git.current_branch() != self.current_branch:
            git.run(['checkout', self.current_branch])

    def show_info(self):
        """Show some info about what's being deployed."""
        config = self.config
        options = self.options

        result = remote(
            config, 'readlink {remote.path.env}', echo=False, hide='all', abort_on_failure=False)
        active_path = result.stdout.strip()

        printer.header('Preparing to deploy {name} to {env} ({remote.host})'.format_map(config))
        if active_path:
            active_version = posixpath.basename(active_path)
            printer.error('Active version: {} ({})'.format(active_version, active_path))
        else:
            printer.warning('There is no active version')
        printer.success('New version: {version} ({remote.build.dir})'.format_map(config))

        printer.info('Configuration:')
        show_config(config, defaults=False)
        printer.warning('\nPlease review the configuration above.')

        if not options['migrate']:
            printer.warning(
                '\nNOTE: Migrations are not run by default; pass --migrate to run them\n')

    def confirm(self):
        """Give ourselves a chance to change our minds."""
        if not confirm(self.config, 'Continue with deployment of version {version} to {env}?'):
            abort(message='Deployment aborted')

    # Local

    def do_local_preprocessing(self):
        """Prepare for deployment."""
        config = self.config
        options = self.options

        if options['version']:
            git.run(['checkout', options['version']])
            printer.header('Attempting to create a clean local install for version...')
            clean(config)
            install(config)

        self.make_build_dir()
        if self.options['build_static']:
            self.build_static()
        self.make_dists()
        self.copy_files()
        self.create_archive()

    def make_build_dir(self):
        """Make the local build directory."""
        build_dir = self.build_dir
        if os.path.isdir(build_dir):
            printer.header(
                'Removing existing build directory: {build_dir}...'.format_map(locals()))
            shutil.rmtree(build_dir)
        printer.header('Creating build directory: {build_dir}'.format_map(locals()))
        os.makedirs(build_dir)
        os.makedirs(os.path.join(build_dir, 'dist'))
        os.makedirs(os.path.join(build_dir, 'static'))
        os.makedirs(os.path.join(build_dir, 'wsgi'))

    def build_static(self):
        """Process static files and collect them.

        This runs things like the LESS preprocessor, RequireJS, etc, and
        then collects all static assets into a single directory.

        """
        printer.header('Building static files...')
        static_root = self.config.path.build.static_root
        build_static(self.config, collect=False)
        collectstatic(self.config, static_root=static_root, hide='stdout')

    def make_dists(self):
        printer.header('Making source distributions...')
        config = self.config
        options = self.options
        dist_dir = config.path.build.dist
        make_dist(config, '.', dist_dir=dist_dir)
        for path in options['deps']:
            make_dist(config, path, dist_dir)
        urlretrieve(
            'https://github.com/PSU-OIT-ARC/arctasks/archive/master.tar.gz',
            os.path.join(dist_dir, 'psu.oit.arc.tasks-0.0.0.tar.gz'))

    def copy_files(self):
        config = self.config
        build_dir = self.build_dir

        copy_file_local(config, 'local.base.cfg', build_dir)
        copy_file_local(config, config.local_settings_file, os.path.join(build_dir, 'local.cfg'))
        copy_file_local(config, config.wsgi_file, os.path.join(build_dir, 'wsgi'))

        # Copy requirements file. If a frozen requirements files exists,
        # copy that; if it doesn't, copy a default requirements file.
        destination_path = os.path.join(build_dir, 'requirements.txt')
        if os.path.isfile('requirements-frozen.txt'):
            copy_file_local(config, 'requirements-frozen.txt', destination_path)
        else:
            path = 'arctasks:templates/requirements.txt.template'
            copy_file_local(config, path, destination_path, template=True)

        # Copy scripts
        kwargs = dict(template=True, mode=0o770)
        copy_file_local(config, '{remote.build.manage_template}', build_dir, **kwargs)
        copy_file_local(config, '{remote.build.restart_template}', build_dir, **kwargs)
        copy_file_local(config, '{remote.build.runcommands_template}', build_dir, **kwargs)

        # Copy RunCommands commands & config
        if os.path.exists('commands.py'):
            copy_file_local(config, 'commands.py', build_dir)

        if os.path.exists('commands.cfg'):
            commands_config = ConfigParser(interpolation=ExtendedInterpolation())
            with open('commands.cfg') as commands_file:
                commands_config.read_file(commands_file)
            extra_config = {
                'version': config.version,
                'local_settings_file': config.remote.build.local_settings_file,
                'deployed_at': self.started.isoformat(),
            }
            extra_config = {k: json.dumps(v) for (k, v) in extra_config.items()}
            commands_config['DEFAULT'].update(extra_config)
            temp_fd, temp_file = tempfile.mkstemp(text=True)
            with os.fdopen(temp_fd, 'w') as t:
                commands_config.write(t)
            copy_file_local(config, temp_file, os.path.join(build_dir, 'commands.cfg'))

        if self.options['provision']:
            # Download and copy virtualenv
            tarball_path = os.path.join(build_dir, 'virtualenv.tgz')
            urlretrieve(config.virtualenv.download_url, tarball_path)
            with tarfile.open(tarball_path, 'r') as tarball:
                tarball.extractall(build_dir)
            os.remove(tarball_path)
            os.rename(
                os.path.join(build_dir, config.virtualenv.base_name),
                os.path.join(build_dir, 'virtualenv'))

    def create_archive(self):
        printer.header('Creating archive...')
        with tarfile.open(self.archive_path, mode='w:gz') as tarball:
            tarball.add(self.build_dir, self.config.version)

    def push(self):
        printer.header('Pushing archive...')
        config = self.config
        options = self.options
        build_root = self.remote_build_root
        build_dir = self.remote_build_dir

        if self.options['overwrite']:
            remote(config, ('rm -rf', build_dir), host='hrimfaxi.oit.pdx.edu')

        copy_file(self.config, self.archive_path, self.config.remote.build.root, quiet=True)

        remote(config, (
            'tar xvf', os.path.basename(self.archive_path),
        ), cd=build_root, hide='stdout')

        if options['static']:
            remote(config, (
                'rsync -rlqtvz --exclude staticfiles.json static/ {remote.path.static}',
            ), cd=build_dir)

    # Remote

    remote_commands = (
        'provision',
        'wheels',
        'install',
        'migrate',
        'make_active',
        'set_permissions',
    )

    def do_remote_commands(self):
        """Build the new deployment environment."""
        for remote_command in self.remote_commands:
            if self.options[remote_command]:
                getattr(self, remote_command)()

    def provision(self):
        printer.header('Provisioning...')
        remote(self.config, (
            'test -d {remote.build.venv} ||',
            '{remote.bin.python} {remote.build.dir}/virtualenv/virtualenv.py',
            '-p python{python.version}',
            '{remote.build.venv}'
        ))

    def wheels(self):
        """Build and cache packages (as wheels)."""
        printer.header('Building wheels...')
        config = self.config
        options = self.options
        wheel_dir = config.remote.pip.wheel_dir
        paths_to_remove = []
        for dist in options['remove_distributions']:
            path = '/'.join((wheel_dir, '{dist}*'.format(dist=dist.replace('-', '_'))))
            paths_to_remove.append(path)
        remote(config, ('rm -f', paths_to_remove))
        remote(config, (
            'LANG=en_US.UTF-8',
            '{remote.build.pip} wheel',
            '--wheel-dir {remote.pip.wheel_dir}',
            '--cache-dir {remote.pip.cache_dir}',
            '--find-links {remote.build.dist}',
            '--find-links {remote.pip.find_links}',
            '--disable-pip-version-check',
            '-r {remote.build.dir}/requirements.txt',
        ))

    def install(self):
        """Install new version in deployment environment."""
        printer.header('Installing...')
        config = self.config
        options = self.options

        uninstall_commands = []
        for dist in options['remove_distributions']:
            uninstall_commands.append(
                '{config.remote.build.pip} uninstall -y {dist}'.format_map(locals()))
        if uninstall_commands:
            remote(config, '; '.join(uninstall_commands), abort_on_failure=False)

        remote(config, (
            '{remote.build.pip} install',
            '--no-index',
            '--find-links {remote.pip.wheel_dir}',
            '--disable-pip-version-check',
            '--no-compile',
            '-r {remote.build.dir}/requirements.txt',
        ))

    def migrate(self):
        """Run database migrations."""
        printer.header('Running migrations...')
        remote_manage(self.config, 'migrate')

    def make_active(self):
        """Make the new version the active version.

        The default version updates the ``env`` symlink to point at the
        build directory created by :func:`provision`.

        Note that this will cause mod_wsgi to restart automatically due
        to its restart-on-touch functionality. The call to `restart` is
        redundant, but it's left in for clarity.

        """
        printer.header('Linking new version and restarting...')
        config = self.config
        link(config, config.version)
        restart(config)

    def set_permissions(self):
        """Explicitly, recursively chmod remote build directories.

        Permissions are updated after restarting because this could take
        a while. The chmod command is run in the background because we don't
        want to sit around waiting, and we assume it will succeed.

        """
        printer.header('Setting permissions in background...')

        def chmod(mode, where, options='-R', host='hrimfaxi.oit.pdx.edu'):
            args = (options, mode, where)
            local(self.config, (
                'ssh -f', host,
                'sudo -u {service.user} sh -c "nohup chmod', args, '>/dev/null 2>&1 &"',
            ))

        chmod('ug=rwX,o-rwx', '{remote.build.dir} {remote.path.log_dir} {remote.path.static}')


@command(default_env='stage', timed=True)
def deploy(config, version=None, deployer_class=None, provision=True, overwrite=False, push=True,
           static=True, build_static=True, deps=(), remove_distributions=(), wheels=True,
           install=True, push_config=True, migrate=False, make_active=True, set_permissions=True):
    """Deploy a new version.

    All of the command options are used to construct a :class:`Deployer`,
    then the deployer's `run` method is called. To implement a different
    deployment strategy, pass an alternate ``deployer_class``. Such a
    class must accept a ``config`` arg plus arbitrary keyword args (which
    it is free to ignore).

    """
    if deployer_class is None:
        deployer_class = deploy.deployer_class
    deployer_class = load_object(deployer_class)
    deployer = deployer_class(
        config,
        version=version,
        provision=provision,
        overwrite=overwrite,
        push=push,
        static=static,
        build_static=build_static,
        deps=deps,
        remove_distributions=remove_distributions,
        wheels=wheels,
        install=install,
        push_config=push_config,
        migrate=migrate,
        make_active=make_active,
        set_permissions=set_permissions,
    )
    try:
        deployer.run()
    except KeyboardInterrupt:
        abort(message='\nDeployment aborted')


deploy.deployer_class = Deployer
deploy.set_deployer_class = lambda class_: setattr(deploy, 'deployer_class', class_)


def get_active_version(config, **kwargs):
    kwargs.setdefault('abort_on_failure', False)
    kwargs.setdefault('hide', 'stdout')
    result = remote(config, 'readlink {remote.path.env}', **kwargs)
    active_version = result.stdout.strip() if result else None
    return result, active_version


@command(
    env=True,
    config={
        'remote.host': 'hrimfaxi.oit.pdx.edu',
    },
    help={
        'rm': 'Remove the specified build(s)',
        'yes': 'Skip confirmations',
    })
def builds(config, active=False, rm=(), yes=False):
    """List/manage builds on remote host.

    --active shows the version of the currently-deployed build
    --rm {version} removes the specified build
    --yes disables confirmation for --rm

    When no options are passed, a list of builds is displayed.

    """
    env = config.env
    build_root = config.remote.build.root

    if rm:
        rm = [rm] if isinstance(rm, str) else rm
        build_dirs = ['{build_root}/{v}'.format(build_root=build_root, v=v) for v in rm]
        cmd = ' && '.join('test -d {d}'.format(d=d) for d in build_dirs)
        result = remote(config, cmd, echo=False, abort_on_failure=False)
        if result.failed:
            printer.error('Build directory not found')
        else:
            cmd = 'rm -r {dirs}'.format(dirs=' '.join(build_dirs))
            printer.header('The following builds will be removed:')
            for d in build_dirs:
                print(d)
            prompt = 'Remove builds?'
            if yes or confirm(config, prompt, color='error', yes_values=('yes',)):
                remote(config, cmd)
    else:
        if active:
            header = 'Active version for {env} (in {build_root}):'
        else:
            header = 'Builds for {env} (in {build_root}; newest first):'

        printer.header(header.format_map(locals()))

        data = []

        _, active_version = get_active_version(config)

        # Get path and timestamp of last modification for each build
        # directory.
        #
        # Example stat entry:
        #
        #    "/vol/www/xyz/builds/stage/1.0.0/ 1453426316"
        stat_path = '{build_root}/*/'.format_map(locals())
        result = remote(config, ('stat -c "%n %Y"', stat_path), echo=False, hide='stdout')

        if result and result.stdout_lines:
            # Parse each stat entry into path, base name, timestamp.
            for line in result.stdout_lines:
                path, timestamp = line.split(' ', 1)
                path = path.rstrip(posixpath.sep)
                base_name = posixpath.basename(path)
                timestamp = datetime.fromtimestamp(int(timestamp))
                data.append((path, base_name, timestamp))

            # Sort entries by timestamp.
            data = sorted(data, key=lambda item: item[2], reverse=True)

            # Print the builds in timestamp order (newest first).
            longest = max(len(d[1]) for d in data)
            for d in data:
                path, version, timestamp = d
                is_active = path == active_version
                out = ['{0:<{longest}} {1}'.format(version, timestamp, longest=longest)]
                if is_active and not active:
                    out.append('[active]')
                out = ' '.join(out)
                if is_active:
                    printer.success(out)
                elif not active:
                    print(out)
        else:
            printer.warning('No {env} builds found in {build_root}'.format_map(locals()))

        return active_version, data


@command(
    env=True,
    config={
        'remote.host': 'hrimfaxi.oit.pdx.edu',
        'defaults.remote.timeout': None,
    })
def clean_builds(config, keep=3):
    if keep < 1:
        abort(1, 'You have to keep at least the active version')

    build_root = config.remote.build.root

    active_version, versions = builds(config)
    versions = [item[1] for item in versions]

    # Move active version to beginning to ensure it's not removed
    if active_version in versions:
        versions.remove(active_version)
        versions.insert(0, active_version)

    versions_to_keep = versions[:keep]
    versions_to_remove = versions[keep:]

    if versions_to_keep:
        printer.success('\nVersions that will be kept:')
        print(', '.join(versions_to_keep))

    if versions_to_remove:
        versions_to_remove_str = ', '.join(versions_to_remove)
        printer.danger('\nVersions that will be removed from {build_root}:'.format_map(locals()))
        print(versions_to_remove_str)
        if confirm(config, '\nReally remove these versions?', yes_values=('really',)):
            printer.danger('Removing {0}...'.format(versions_to_remove_str))
            rm_paths = [posixpath.join(build_root, v) for v in versions_to_remove]
            remote(config, ('rm -r', rm_paths), echo=True)
            builds(config)
    else:
        printer.warning('\nNo versions to remove')


@command(
    config={
        'remote.host': 'hrimfaxi.oit.pdx.edu',
    },
)
def link(config, version, staticfiles_manifest=True, old_style=None):
    config = config.copy(version=version)

    cmd = [
        'test -d {remote.build.dir}',
        'ln -sfn {remote.build.dir} {remote.path.env}',
    ]

    if staticfiles_manifest:
        cmd.append(
            'ln -sfn {remote.build.static}/staticfiles.json {remote.path.static}/staticfiles.json')

    remote(config, ' && '.join(cmd))

    # XXX: This supports old-style deployments where the media and
    #      static directories are in the source directory.
    if old_style:
        remote(config, (
            'ln -sfn {remote.path.media} {remote.build.dir}/media &&',
            'ln -sfn {remote.path.static} {remote.build.dir}/static',
        ))


@command
def push_static(config, build=True, dry_run=False, delete=False, echo=False, hide=None):
    static_root = config.path.build.static_root
    if build:
        build_static(config, static_root=static_root)
    if not static_root.endswith(os.sep):
        static_root += os.sep
    rsync(
        config, static_root, config.remote.path.static, dry_run=dry_run, delete=delete, echo=echo,
        hide=hide, excludes=('staticfiles.json',))
    manifest = os.path.join(static_root, 'staticfiles.json')
    if os.path.isfile(manifest):
        copy_file(config, manifest, config.remote.build.static)
        remote(config, (
            'ln -sf',
            '{remote.build.static}/staticfiles.json',
            '{remote.path.static}/staticfiles.json',
        ))


@command
def restart(config, get=True, scheme='https', path='/', show=False):
    settings = django.get_settings(config)
    remote(config, '$(readlink {remote.path.env})/restart')
    if get:
        host = getattr(settings, 'DOMAIN_NAME', None)
        if host is None:
            host = settings.ALLOWED_HOSTS[0]
            host = host.lstrip('.')
        else:
            printer.warning(
                'The DOMAIN_NAME setting is deprecated; '
                'set the first entry in ALLOWED_HOSTS to the canonical host instead')
        if not path.startswith('/'):
            path = '/{path}'.format(path=path)
        url = '{scheme}://{host}{path}'.format_map(locals())
        printer.info('Getting {url}...'.format_map(locals()))
        urlopen_args = {}
        if sys.version_info[:2] > (3, 3):
            urlopen_args['context'] = ssl.SSLContext()
        try:
            with urlopen(url, **urlopen_args) as url_fp:
                data = url_fp.read()
        except (HTTPError, URLError) as exc:
            abort(1, 'Failed to retrieve {url}: {exc}'.format_map(locals()))
        if show:
            print(data.decode('utf-8'))


# Utilities


def copy_file_local(config, path, destination_path, template=False, template_type=None, mode=None):
    path = abs_path(path, format_kwargs=config)
    destination_path = abs_path(destination_path, format_kwargs=config)

    if template:
        with open(path) as in_fp:
            contents = in_fp.read()

        if template_type in (None, 'format'):
            contents = contents.format_map(config)
        elif template_type == 'string':
            template = string.Template(contents)
            contents = template.substitute(config)
        else:
            raise ValueError('Unrecognized template type: %s' % template_type)

        prefix = '%s-' % config.package
        suffix = '-%s' % os.path.basename(path)
        temp_fd, temp_path = tempfile.mkstemp(prefix=prefix, suffix=suffix, text=True)

        with os.fdopen(temp_fd, 'w') as temp_file:
            temp_file.write(contents)

        if os.path.isdir(destination_path):
            base_name = os.path.basename(path)
            name, ext = os.path.splitext(base_name)
            if ext == '.template':
                destination_path = os.path.join(destination_path, name)

        copy_path = shutil.copy(temp_path, destination_path)
        os.remove(temp_path)
    else:
        copy_path = shutil.copy(path, destination_path)

    if mode is not None:
        os.chmod(copy_path, mode)

    return copy_path


def make_dist(config, path, dist_dir=None):
    cmd = [sys.executable, 'setup.py sdist']
    if dist_dir:
        cmd.append('-d {dist_dir}'.format_map(locals()))
    printer.info('Making sdist in {path}; saving to {dist_dir}...'.format_map(locals()))
    local(config, cmd, cd=path, hide='all')
