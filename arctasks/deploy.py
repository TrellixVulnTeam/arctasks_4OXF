import json
import os
import posixpath
import shutil
import sys
import tempfile
from configparser import ConfigParser, ExtendedInterpolation
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import urlretrieve

from runcommands import command
from runcommands.commands import show_config, local, remote
from runcommands.util import abort, as_list, confirm, load_object, printer

from . import django
from . import git
from .base import clean, install
from .remote import manage as remote_manage, rsync, copy_file
from .static import build_static


@command
def provision(config, overwrite=False):
    build_dir = config.remote.build.dir
    venv = config.remote.build.venv

    if overwrite:
        # Remove existing build directory if present
        remote(config, ('rm -rf', build_dir))

    # Make build directories
    build_dirs = ['{remote.build.dir}', '{remote.build.dist}']
    if config.remote.build.wsgi_dir:
        build_dirs.append('{remote.build.wsgi_dir}')
    remote(config, ('mkdir -p -m ug=rwx,o-rwx', build_dirs))

    # Create virtualenv for build
    result = remote(config, ('test -d', venv), abort_on_failure=False)
    if result.failed:
        remote(config, (
            'curl -L -o {virtualenv.tarball_name} {virtualenv.download_url}',
            '&& tar xvfz {virtualenv.tarball_name}',
        ), cd='{remote.build.dir}', hide='all')
        remote(config, (
            '{remote.bin.python} virtualenv.py {remote.build.venv}'
        ), cd='{remote.build.dir}/{virtualenv.base_name}')

    # Provision virtualenv with basics
    pip_install = (config.remote.build.pip, 'install')
    pip_upgrade = pip_install + ('--upgrade',)
    has_pip_version = config.pip.get('version')
    remote(config, (
        (pip_upgrade, 'setuptools'), '&&',
        (pip_install, '"pip=={pip.version}"') if has_pip_version else (pip_upgrade, 'pip'), '&&',
        (pip_install, 'wheel'),
    ))


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
        self.config = config
        self.options = self.init_options(options)
        self.current_branch = git.current_branch()
        version = self.options['version']
        if version is not None:
            self.config = config._clone(version=version)

    def init_options(self, options):
        config = self.config
        remove_distributions = as_list(options.get('remove_distributions'))
        options['remove_distributions'] = [config.distribution] + remove_distributions
        return options

    def run(self):
        """Deploy."""
        self.show_info()
        self.confirm()
        self.do_local_preprocessing()
        self.do_remote_commands()
        if git.current_branch() != self.current_branch:
            git.run(['checkout', self.current_branch])

    def show_info(self):
        """Show some info about what's being deployed."""
        config = self.config
        opts = self.options

        result = remote(
            config, 'readlink {remote.path.env}', echo=False, hide='all', abort_on_failure=False)
        active_path = result.stdout.strip()

        printer.header('Preparing to deploy {name} to {env} ({remote.host})'.format(**config))
        if active_path:
            active_version = posixpath.basename(active_path)
            printer.error('Active version: {} ({})'.format(active_version, active_path))
        else:
            printer.warning('There is no active version')
        printer.success('New version: {version} ({remote.build.dir})'.format(**config))

        printer.info('Configuration:')
        show_config(config, defaults=False, initial_level=1)
        printer.warning('\nPlease review the configuration above.')

        if not opts['migrate']:
            printer.warning(
                '\nNOTE: Migrations are not run by default; pass --migrate to run them\n')

    def confirm(self):
        """Give ourselves a chance to change our minds."""
        if not confirm(self.config, 'Continue with deployment of version {version} to {env}?'):
            abort(message='Deployment aborted')

    # Local

    def do_local_preprocessing(self):
        """Prepare for deployment."""
        opts = self.options
        self.make_build_dir()
        if opts['version']:
            git.run(['checkout', opts['version']])
            printer.header('Attempting to create a clean local install for version...')
            clean(self.config)
            install(self.config)
        if opts['static'] and opts['build_static']:
            self.build_static()

    def make_build_dir(self):
        """Make the local build directory."""
        build_dir = self.config.path.build.root
        if os.path.isdir(build_dir):
            printer.header('Removing existing build directory: {build_dir} ...'.format(**locals()))
            shutil.rmtree(build_dir)
        printer.header('Creating build directory: {build_dir}'.format(**locals()))
        os.makedirs(build_dir)

    def build_static(self):
        """Process static files and collect them.

        This runs things like the LESS preprocessor, RequireJS, etc, and
        then collects all static assets into a single directory.

        """
        printer.header('Building static files...')
        build_static(self.config, static_root='{path.build.static_root}')

    # Remote

    remote_commands = (
        'provision',
        'push',
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
        provision(self.config, self.options['overwrite'])

    def push(self):
        printer.header('Pushing app...')
        push_app(self.config, hide='all')
        if self.options['push_config']:
            self.push_config()
        if self.options['static']:
            printer.header('Pushing static files...')
            push_static(self.config)

    def wheels(self):
        """Build and cache packages (as wheels)."""
        printer.header('Building wheels...')
        config, opts = self.config, self.options
        wheel_dir = config.remote.pip.wheel_dir
        paths_to_remove = []
        for dist in opts['remove_distributions']:
            path = '/'.join((wheel_dir, '{dist}*'.format(dist=dist.replace('-', '_'))))
            paths_to_remove.append(path)
        remote(config, ('rm -f', paths_to_remove))
        result = remote(config, 'ls {remote.build.dist}', echo=False, hide='stdout')
        dists = result.stdout.strip().splitlines()
        for dist in dists:
            if dist.startswith(config.distribution):
                break
        else:
            abort(1, 'Could not find source distribution for {distribution}'.format(**config))
        remote(config, (
            '{remote.build.pip} wheel',
            '--wheel-dir {remote.pip.wheel_dir}',
            '--cache-dir {remote.pip.cache_dir}',
            '--find-links {remote.build.dir}/dist',
            '--find-links {remote.pip.find_links}',
            '--disable-pip-version-check',
            '-r {remote.build.dir}/requirements.txt',
        ))

    def install(self):
        """Install new version in deployment environment."""
        printer.header('Installing...')
        config, opts = self.config, self.options
        for dist in opts['remove_distributions']:
            remote(config, ('{remote.build.pip} uninstall -y', dist), abort_on_failure=False)
        remote(config, (
            '{remote.build.pip} install',
            '--ignore-installed',
            '--no-index',
            '--find-links {remote.pip.wheel_dir}',
            '--disable-pip-version-check',
            '--no-compile',
            '-r {remote.build.dir}/requirements.txt',
        ))

    def push_config(self):
        """Copy command config, requirements, settings, scripts, etc."""
        printer.header('Pushing config...')
        config = self.config
        exe_mode = 'ug+rwx,o-rwx'
        self._push_command_config(exe_mode)
        copy_file(
            config, '{remote.build.manage_template}', '{remote.build.manage}', template=True,
            mode=exe_mode)
        copy_file(
            config, '{remote.build.restart_template}', '{remote.build.restart}', template=True,
            mode=exe_mode)
        copy_file(config, 'local.base.cfg', '{remote.build.dir}')
        copy_file(config, '{local_settings_file}', '{remote.build.local_settings_file}')
        if config.remote.build.wsgi_file:
            copy_file(config, '{wsgi_file}', '{remote.build.wsgi_file}')

        # Copy requirements file. If a frozen requirements files exists,
        # copy that; if it doesn't, copy a default requirements file.
        remote_path = '{remote.build.dir}/requirements.txt'
        if os.path.isfile('requirements-frozen.txt'):
            copy_file(config, 'requirements-frozen.txt', remote_path)
        else:
            copy_file(
                config, 'arctasks:templates/requirements.txt.template', remote_path, template=True)

    def _push_command_config(self, exe_mode):
        # This is split out of push_config because it's somewhat complex
        config = self.config

        # Wrapper for RunCommands script that sets the default env to
        # the env of the deployment and adds the virtualenv's bin
        # directory to the front of $PATH.
        copy_file(
            config, 'arctasks:templates/runcommands.template', '{remote.build.dir}/runcommands',
            template=True, mode=exe_mode)

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
            copy_file(config, temp_file, '{remote.build.dir}/commands.cfg')

        if os.path.exists('commands.py'):
            copy_file(config, 'commands.py', '{remote.build.dir}')

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
           static=True, build_static=True, remove_distributions=None, wheels=True, install=True,
           push_config=True, migrate=False, make_active=True, set_permissions=True):
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


@command(help={
    'rm': 'Remove the specified build',
    'yes': 'Skip confirmations',
})
def builds(config, active=False, rm=None, yes=False):
    """List/manage builds on remote host.

    --active shows the version of the currently-deployed build
    --rm {version} removes the specified build
    --yes disables confirmation for --rm

    When no options are passed, a list of builds is displayed.

    """
    build_root = config.remote.build.root
    if active:
        result = remote(config, 'readlink {remote.path.env}', abort_on_failure=False)
        if result.failed:
            printer.error('Could not read link for active version')
    elif rm:
        versions = as_list(rm)
        build_dirs = ['{build_root}/{v}'.format(build_root=build_root, v=v) for v in versions]
        cmd = ' && '.join('test -d {d}'.format(d=d) for d in build_dirs)
        result = remote(config, cmd, echo=False, abort_on_failure=False)
        if result.failed:
            printer.error('Build directory not found')
        else:
            cmd = 'rm -r {dirs}'.format(dirs=' '.join(build_dirs))
            printer.header('The following builds will be removed:')
            for d in build_dirs:
                print(d)
            prompt = 'Remove builds?'.format(cmd=cmd)
            if yes or confirm(config, prompt, color='error', yes_values=('yes',)):
                remote(config, cmd)
    else:
        active = remote(
            config, 'readlink {remote.path.env}', abort_on_failure=False, hide='stdout')
        active = active.stdout.strip() if active.succeeded else ''
        printer.header('Builds for {env} (in {remote.build.root}; newest first):'.format(**config))
        # Get a list of all the build directories.
        result = remote(config, (
            'find', build_root, '-mindepth 1 -maxdepth 1 -type d'
        ), cd='/', echo=False, hide='stdout')
        if result.stdout_lines:
            dirs = ' '.join(result.stdout_lines)
            # Get path and timestamp of last modification for each build
            # directory.
            # Example stat entry:
            #    "/vol/www/project_x/builds/stage/1.0.0 1453426316"
            result = remote(
                config, 'stat -c "%n %Y" {dirs}'.format(dirs=dirs), echo=False, hide='all')
            data = result.stdout.strip().splitlines()
            # Parse each stat entry into (path, timestamp).
            data = [d.split(' ', 1) for d in data]
            # Parse further into (full path, base name, datetime object).
            data = [
                (d[0], posixpath.basename(d[0]), datetime.fromtimestamp(int(d[1])))
                for d in data
            ]
            # Sort entries by timestamp.
            data = sorted(data, key=lambda item: item[2], reverse=True)
            longest = max(len(d[1]) for d in data)
            for d in data:
                path, version, timestamp = d
                is_active = path == active
                out = ['{0:<{longest}} {1}'.format(version, timestamp, longest=longest)]
                if is_active:
                    out.append('[active]')
                out = ' '.join(out)
                if is_active:
                    printer.success(out)
                else:
                    print(out)
        else:
            printer.warning('No {env} builds found in {remote.build.root}'.format(**config))


@command
def clean_builds(config, keep=3):
    if keep < 1:
        abort(1, 'You have to keep at least the active version')
    result = remote(config, 'readlink {remote.path.env}', hide='stdout')
    active_path = result.stdout.strip()
    active_version = posixpath.basename(active_path)
    builds(config)
    result = remote(config, 'ls -c {remote.build.root}', hide='stdout')
    versions = result.stdout.strip().splitlines()
    if active_version in versions:
        versions.remove(active_version)
        versions.insert(0, active_version)
    versions_to_keep = versions[:keep]
    versions_to_remove = versions[keep:]
    if versions_to_keep:
        printer.success('Versions that will be kept:')
        print(', '.join(versions_to_keep))
    if versions_to_remove:
        versions_to_remove_str = ', '.join(versions_to_remove)
        printer.danger('Versions that will be removed from {remote.build.root}:'.format(**config))
        print(versions_to_remove_str)
        if confirm(config, 'Really remove these versions?', yes_values=('really',)):
            printer.danger('Removing {0}...'.format(versions_to_remove_str))
            rm_paths = [posixpath.join(config.remote.build.root, v) for v in versions_to_remove]
            remote(config, ('rm -r', rm_paths), 'hrimfaxi.oit.pdx.edu', echo=True)
            builds(config)
    else:
        printer.warning('No versions to remove')


@command
def link(config, version, staticfiles_manifest=True, old_style=None):
    build_dir = '{config.remote.build.root}/{version}'.format_map(locals())

    result = remote(config, ('test -d', build_dir), abort_on_failure=False)
    if not result.succeeded:
        abort(1, 'Build directory {build_dir} does not exist'.format_map(locals()))

    remote(config, ('ln -sfn', build_dir, '{remote.path.env}'))

    # Link the specified version's static manifest
    if staticfiles_manifest:
        remote(config, (
            'ln -sf',
            '{build_dir}/staticfiles.json'.format_map(locals()),
            '{remote.path.static}/staticfiles.json'
        ))

    # XXX: This supports old-style deployments where the media and
    #      static directories are in the source directory.
    if old_style:
        media_dir = '{build_dir}/media'.format_map(locals())
        static_dir = '{build_dir}/static'.format_map(locals())
        remote(config, ('ln -sfn {remote.path.root}/media/{env}', media_dir))
        remote(config, ('ln -sfn {remote.path.root}/static/{env}', static_dir))


@command
def push_app(config, deps=None, echo=False, hide=None):
    sdist = 'setup.py sdist -d {path.build.dist}'
    local(config, (sys.executable, sdist), echo=echo, hide=hide)
    for path in as_list(deps):
        local(config, (sys.executable, sdist), cd=path, echo=echo, hide=hide)
    local(config, (
        '{bin.pip}',
        'wheel',
        '--wheel-dir {path.build.dist}',
        '--find-links {remote.pip.find_links}',
        'https://github.com/PSU-OIT-ARC/arctasks/archive/master.tar.gz',
    ), echo=echo, hide=hide)
    remote(config, 'rm -f {remote.build.dist}/*')
    rsync(config, '{path.build.dist}/*', '{remote.build.dist}')


@command
def push_static(config, build=True, dry_run=False, delete=False, echo=False, hide='stdout'):
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
        copy_file(config, manifest, config.remote.build.dir)


@command
def restart(config, get=True, scheme='http', path='/'):
    settings = django.get_settings(config)
    remote(config, '{remote.build.restart}')
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
        try:
            urlretrieve(url, os.devnull)
        except (HTTPError, URLError) as exc:
            abort(1, 'Failed to retrieve {url}: {exc}'.format_map(locals()))
