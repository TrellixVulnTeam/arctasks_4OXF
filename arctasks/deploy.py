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

from . import django
from . import git
from .arctask import arctask
from .base import clean, install
from .config import configure, show_config
from .remote import manage as remote_manage, rsync, copy_file
from .runners import local, remote
from .static import build_static
from .util import abort, as_list, confirm, load_object
from .util import print_header, print_info, print_success, print_warning, print_error, print_danger


@arctask(configured=True)
def provision(ctx, overwrite=False):
    build_dir = ctx.remote.build.dir
    venv = ctx.remote.build.venv
    if overwrite:
        # Remove existing build directory if present
        remote(ctx, ('rm -rf', build_dir))
    # Make build dir
    remote(ctx, (
        'mkdir -p -m ug=rwx,o-rwx',
        '{remote.build.dir} {remote.build.dist} {remote.build.wsgi_dir}',
    ))
    # Create virtualenv for build
    result = remote(ctx, ('test -d', venv), abort_on_failure=False)
    if result.failed:
        remote(ctx, ('{remote.build.make_venv}', venv))
    # Provision virtualenv with basics
    pip = ctx.remote.build.pip
    find_links = ctx.remote.pip.find_links
    remote(ctx, (
        (pip, 'install -U setuptools', '&&'),
        (pip, 'install --find-links', find_links, '"pip=={pip.version}"', '&&'),
        (pip, 'install --find-links', find_links, '--cache-dir {remote.pip.cache_dir} wheel'),
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
            pip/cache/   # Cached package downloads
            pip/wheel/       # Cached package builds
            media/{env}/          # Media files for env (shared across builds)
            static/{env}/         # Static files for env (shared across builds)

    [1] Use {package}/wsgi.py for legacy builds.
    [2] Only necessary for legacy Apache config; only created when the
        ``--old-style`` flag is passed to the :func:`.link` task.

    """

    def __init__(self, ctx, **options):
        self.started = datetime.now()
        self.ctx = ctx
        self.options = self.init_options(options)
        self.current_branch = git.current_branch()
        version = self.options['version']
        if version is not None:
            configure(ctx, ctx.env, version)

    def init_options(self, options):
        ctx = self.ctx
        remove_distributions = as_list(options.get('remove_distributions'))
        options['remove_distributions'] = [ctx.distribution] + remove_distributions
        return options

    def run(self):
        """Deploy."""
        self.show_info()
        self.confirm()
        self.do_local_preprocessing()
        self.do_remote_tasks()
        if git.current_branch() != self.current_branch:
            git.git(['checkout', self.current_branch])

    def show_info(self):
        """Show some info about what's being deployed."""
        ctx = self.ctx
        opts = self.options

        result = remote(
            ctx, 'readlink {remote.path.env}', echo=False, hide=True, abort_on_failure=False)
        active_path = result.stdout.strip()

        print_header('Preparing to deploy {name} to {env} ({remote.host})'.format(**ctx))
        if active_path:
            active_version = posixpath.basename(active_path)
            print_error('Active version: {} ({})'.format(active_version, active_path))
        else:
            print_warning('There is no active version')
        print_success('New version: {version} ({remote.build.dir})'.format(**ctx))

        print_info('Configuration:')
        show_config(ctx, tasks=False, initial_level=1)
        print_warning('\nPlease review the configuration above.')

        if not opts['migrate']:
            print_warning('\nNOTE: Migrations are not run by default; pass --migrate to run them\n')

    def confirm(self):
        """Give ourselves a chance to change our minds."""
        if not confirm(self.ctx, 'Continue with deployment of version {version} to {env}?'):
            abort(message='Deployment aborted')

    # Local

    def do_local_preprocessing(self):
        """Prepare for deployment."""
        opts = self.options
        self.make_build_dir()
        if opts['version']:
            git.git(['checkout', opts['version']])
            print_header('Attempting create a clean local install for version...')
            clean(self.ctx)
            install(self.ctx)
        if opts['static'] and opts['build_static']:
            self.build_static()

    def make_build_dir(self):
        """Make the local build directory."""
        build_dir = self.ctx.path.build.root
        if os.path.isdir(build_dir):
            print_header('Removing existing build directory...')
            shutil.rmtree(build_dir)
        print_header('Creating build dir...')
        os.makedirs(build_dir)

    def build_static(self):
        """Process static files and collect them.

        This runs things like the LESS preprocessor, RequireJS, etc, and
        then collects all static assets into a single directory.

        """
        print_header('Building static files...')
        build_static(self.ctx)

    # Remote

    remote_tasks = (
        'provision',
        'push',
        'wheels',
        'install',
        'migrate',
        'make_active',
        'set_permissions',
    )

    def do_remote_tasks(self):
        """Build the new deployment environment."""
        for task in self.remote_tasks:
            if self.options[task]:
                getattr(self, task)()

    def provision(self):
        print_header('Provisioning...')
        provision(self.ctx, self.options['overwrite'])

    def push(self):
        print_header('Pushing app...')
        push_app(self.ctx)
        if self.options['push_config']:
            self.push_config()
        if self.options['static']:
            print_header('Pushing static files...')
            push_static(self.ctx)

    def wheels(self):
        """Build and cache packages (as wheels)."""
        print_header('Building wheels...')
        ctx, opts = self.ctx, self.options
        wheel_dir = ctx.remote.pip.wheel_dir
        paths_to_remove = []
        for dist in opts['remove_distributions']:
            path = '/'.join((wheel_dir, '{dist}*'.format(dist=dist.replace('-', '_'))))
            paths_to_remove.append(path)
        remote(ctx, ('rm -f', paths_to_remove))
        result = remote(ctx, 'ls {remote.build.dist}', echo=False, hide='stdout')
        dists = result.stdout.strip().splitlines()
        for dist in dists:
            if dist.startswith(ctx.distribution):
                break
        else:
            abort(1, 'Could not find source distribution for {distribution}'.format(**ctx))
        remote(ctx, (
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
        print_header('Installing...')
        ctx, opts = self.ctx, self.options
        for dist in opts['remove_distributions']:
            remote(ctx, ('{remote.build.pip} uninstall -y', dist), abort_on_failure=False)
        remote(ctx, (
            '{remote.build.pip} install',
            '--ignore-installed',
            '--no-index',
            '--find-links {remote.pip.wheel_dir}',
            '--disable-pip-version-check',
            '--no-compile',
            '-r {remote.build.dir}/requirements.txt',
        ))

    def push_config(self):
        """Copy task config, requirements, settings, scripts, etc."""
        print_header('Pushing config...')
        ctx, opts = self.ctx, self.options
        exe_mode = 'ug+rwx,o-rwx'
        self._push_task_config(exe_mode)
        copy_file(
            ctx, '{remote.build.manage_template}', '{remote.build.manage}', template=True,
            mode=exe_mode)
        copy_file(
            ctx, '{remote.build.restart_template}', '{remote.build.restart}', template=True,
            mode=exe_mode)
        copy_file(ctx, 'local.base.cfg', '{remote.build.dir}')
        copy_file(ctx, '{local_settings_file}', '{remote.build.local_settings_file}')
        copy_file(ctx, '{wsgi_file}', '{remote.build.wsgi_file}')

        # Copy requirements file. If a frozen requirements files exists,
        # copy that; if it doesn't, copy a default requirements file.
        remote_path = '{remote.build.dir}/requirements.txt'
        if os.path.isfile('requirements-frozen.txt'):
            copy_file(ctx, 'requirements-frozen.txt', remote_path)
        else:
            copy_file(
                ctx, 'arctasks:templates/requirements.txt.template', remote_path, template=True)

    def _push_task_config(self, exe_mode):
        # This is split out of push_config because it's somewhat complex
        ctx = self.ctx

        # Wrapper for inv script that sets the default env to the env of
        # the deployment and adds the virtualenv's bin directory to the
        # front of $PATH.
        copy_file(
            ctx, 'arctasks:templates/inv.template', '{remote.build.dir}/inv', template=True,
            mode=exe_mode)

        if os.path.exists('tasks.cfg'):
            task_config = ConfigParser(interpolation=ExtendedInterpolation())
            with open('tasks.cfg') as tasks_file:
                task_config.read_file(tasks_file)
            extra_config = {
                'version': ctx.version,
                'local_settings_file': ctx.remote.build.local_settings_file,
                'deployed_at': self.started.isoformat(),
            }
            extra_config = {k: json.dumps(v) for (k, v) in extra_config.items()}
            task_config['DEFAULT'].update(extra_config)
            temp_fd, temp_file = tempfile.mkstemp(text=True)
            with os.fdopen(temp_fd, 'w') as t:
                task_config.write(t)
            copy_file(ctx, temp_file, '{remote.build.dir}/tasks.cfg')

        if os.path.exists('tasks.py'):
            copy_file(ctx, 'tasks.py', '{remote.build.dir}')

    def migrate(self):
        """Run database migrations."""
        print_header('Running migrations...')
        remote_manage(self.ctx, 'migrate')

    def make_active(self):
        """Make the new version the active version.

        The default version updates the ``env`` symlink to point at the
        build directory created by :func:`provision`.

        Note that this will cause mod_wsgi to restart automatically due
        to its restart-on-touch functionality. The call to `restart` is
        redundant, but it's left in for clarity.

        """
        print_header('Linking new version and restarting...')
        ctx = self.ctx
        link(ctx, ctx.version)
        restart(ctx)

    def set_permissions(self):
        """Explicitly, recursively chmod remote build directory.

        Permissions are updated after restarting because this could take
        a while. A screen session is used to run the chmod command
        because we don't want to sit around waiting, and we assume the
        chmod will succeed.

        """
        print_header('Setting permissions in background...')
        remote(self.ctx, (
            'screen -d -m',
            'chmod -R ug=rwX,o-rwx {remote.build.dir} {remote.path.static}'
        ), host='hrimfaxi.oit.pdx.edu')


@arctask(configured='stage', timed=True)
def deploy(ctx, version=None, deployer_class=None, provision=True, overwrite=False, push=True,
           static=True, build_static=True, remove_distributions=None, wheels=True, install=True,
           push_config=True, migrate=False, make_active=True, set_permissions=True):
    """Deploy a new version.

    All of the task options are used to construct a :class:`Deployer`,
    then the deployer's `run` method is called. To implement a different
    deployment strategy, pass an alternate ``deployer_class``. Such a
    class must accept a ``ctx`` arg plus arbitrary keyword args (which
    it is free to ignore).

    """
    if deployer_class is None:
        deployer_class = deploy.deployer_class
    deployer_class = load_object(deployer_class)
    deployer = deployer_class(
        ctx,
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
deploy.set_deployer_class = lambda deployer_class: setattr(deploy, 'deployer_class', deployer_class)


@arctask(configured=True, help={'rm': 'Remove the specified build', 'yes': 'Skip confirmations'})
def builds(ctx, active=False, rm=None, yes=False):
    """List/manage builds on remote host.

    --active shows the version of the currently-deployed build
    --rm {version} removes the specified build
    --yes disables confirmation for --rm

    When no options are passed, a list of builds is displayed.

    """
    build_root = ctx.remote.build.root
    if active:
        result = remote(ctx, 'readlink {remote.path.env}', abort_on_failure=False)
        if result.failed:
            print_error('Could not read link for active version')
    elif rm:
        versions = as_list(rm)
        build_dirs = ['{build_root}/{v}'.format(build_root=build_root, v=v) for v in versions]
        cmd = ' && '.join('test -d {d}'.format(d=d) for d in build_dirs)
        result = remote(ctx, cmd, echo=False, abort_on_failure=False)
        if result.failed:
            print_error('Build directory not found')
        else:
            cmd = 'rm -r {dirs}'.format(dirs=' '.join(build_dirs))
            print_header('The following builds will be removed:')
            for d in build_dirs:
                print(d)
            prompt = 'Remove builds?'.format(cmd=cmd)
            if yes or confirm(ctx, prompt, color='error', yes_values=('yes',)):
                remote(ctx, cmd)
    else:
        active = remote(ctx, 'readlink {remote.path.env}', abort_on_failure=False)
        active = active.stdout.strip() if active.ok else ''
        print_header('Builds for {env} (in {remote.build.root}; newest first):'.format(**ctx))
        # Get a list of all the build directories.
        dirs = remote(ctx, (
            'find', build_root, '-mindepth 1 -maxdepth 1 -type d'
        ), cd='/', echo=False, hide='stdout')
        result = dirs.stdout.strip().splitlines()
        if result:
            dirs = ' '.join(result)
            # Get path and timestamp of last modification for each build
            # directory.
            # Example stat entry:
            #    "/vol/www/project_x/builds/stage/1.0.0 1453426316"
            result = remote(
                ctx, 'stat -c "%n %Y" {dirs}'.format(dirs=dirs), echo=False, hide=True)
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
                    print_success(out)
                else:
                    print(out)
        else:
            print_warning('No {env} builds found in {remote.build.root}'.format(**ctx))


@arctask(configured=True)
def clean_builds(ctx, keep=3):
    if keep < 1:
        abort(1, 'You have to keep at least the active version')
    result = remote(ctx, 'readlink {remote.path.env}', hide='stdout')
    active_path = result.stdout.strip()
    active_version = posixpath.basename(active_path)
    builds(ctx)
    result = remote(ctx, 'ls -c {remote.build.root}', hide='stdout')
    versions = result.stdout.strip().splitlines()
    if active_version in versions:
        versions.remove(active_version)
        versions.insert(0, active_version)
    versions_to_keep = versions[:keep]
    versions_to_remove = versions[keep:]
    if versions_to_keep:
        print_success('Versions that will be kept:')
        print(', '.join(versions_to_keep))
    if versions_to_remove:
        versions_to_remove_str = ', '.join(versions_to_remove)
        print_danger('Versions that will be removed from {remote.build.root}:'.format(**ctx))
        print(versions_to_remove_str)
        if confirm(ctx, 'Really remove these versions?', yes_values=('really',)):
            print_danger('Removing {0}...'.format(versions_to_remove_str))
            rm_paths = [posixpath.join(ctx.remote.build.root, v) for v in versions_to_remove]
            remote(ctx, ('rm -r', rm_paths), echo=True)
            builds(ctx)
    else:
        print_warning('No versions to remove')


@arctask(configured=True)
def link(ctx, version, staticfiles_manifest=True, old_style=None):
    build_dir = '{remote.build.root}/{v}'.format(v=version, **ctx)
    remote(ctx, ('ln', '-sfn', build_dir, '{remote.path.root}/{env}'))

    # Link the specified version's static manifest
    if staticfiles_manifest:
        remote(ctx, (
            'ln -sf',
            '{remote.build.dir}/staticfiles.json',
            '{remote.path.static}/staticfiles.json'
        ))

    # XXX: This supports old-style deployments where the media and
    #      static directories are in the source directory.
    if old_style:
        media_dir = '{build_dir}/media'.format(build_dir=build_dir)
        static_dir = '{build_dir}/static'.format(build_dir=build_dir)
        remote(ctx, ('ln -sfn {remote.path.root}/media/{env}', media_dir))
        remote(ctx, ('ln -sfn {remote.path.root}/static/{env}', static_dir))


@arctask(configured=True)
def push_app(ctx, deps=None):
    sdist = 'setup.py sdist -d {path.build.dist}'
    local(ctx, (sys.executable, sdist), hide='stdout')
    for path in as_list(deps):
        local(ctx, (sys.executable, sdist), hide='stdout', cd=path)
    local(ctx, (
        '{bin.pip}',
        'wheel',
        '--wheel-dir {path.build.dist}',
        'https://github.com/PSU-OIT-ARC/arctasks/archive/master.tar.gz',
    ))
    remote(ctx, 'rm -f {remote.build.dist}/*')
    rsync(ctx, '{path.build.dist}/*', '{remote.build.dist}')


@arctask(build_static, configured=True)
def push_static(ctx, delete=False):
    static_root = ctx.arctasks.static.build_static.static_root
    if not static_root.endswith(os.sep):
        static_root += os.sep
    rsync(ctx, static_root, ctx.remote.path.static, delete=delete, excludes=('staticfiles.json',))
    manifest = os.path.join(static_root, 'staticfiles.json')
    if os.path.isfile(manifest):
        copy_file(ctx, manifest, ctx.remote.build.dir)


@arctask(configured=True)
def restart(ctx, get=True, scheme='http', path='/'):
    settings = django.get_settings()
    remote(ctx, 'touch {remote.path.wsgi_file}')
    if get:
        host = getattr(settings, 'DOMAIN_NAME', None)
        if host is None:
            host = settings.ALLOWED_HOSTS[0]
            host = host.lstrip('.')
        else:
            print_warning(
                'The DOMAIN_NAME setting is deprecated; '
                'set the first entry in ALLOWED_HOSTS to the canonical host instead')
        if not path.startswith('/'):
            path = '/{path}'.format(path=path)
        url = '{scheme}://{host}{path}'.format_map(locals())
        print_info('Getting {url}...'.format_map(locals()))
        try:
            urlretrieve(url, os.devnull)
        except (HTTPError, URLError) as exc:
            abort(1, 'Failed to retrieve {url}: {exc}'.format_map(locals()))
