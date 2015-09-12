import os
import posixpath
import shutil
import sys
from datetime import datetime
from urllib.request import urlretrieve

from . import django
from .arctask import arctask
from .config import show_config
from .remote import manage as remote_manage, rsync, copy_file
from .runners import local, remote
from .static import build_static
from .util import abort, abs_path, as_list, confirm
from .util import print_header, print_info, print_success, print_warning, print_error, print_danger


@arctask(configured=True)
def provision(ctx, overwrite=False):
    build_dir = ctx.remote.build.dir
    venv = ctx.remote.build.venv
    if overwrite:
        # Remove existing build directory if present
        remote(ctx, ('rm -rf', build_dir, venv))
    # Make build dir
    remote(ctx, (
        'mkdir -p -m ug=rwx,o-rwx',
        '{remote.build.dir} {remote.build.dist} {remote.build.wsgi_dir}',
    ))
    # Create virtualenv for build
    result = remote(ctx, ('test -d', venv), abort_on_failure=False)
    if result.failed:
        remote(ctx, ('virtualenv -p python3', venv))
    # Provision virtualenv with basics
    pip = ctx.remote.build.pip
    find_links = ctx.remote.pip.find_links
    remote(ctx, (
        (pip, 'install -U setuptools'),
        (pip, 'install --find-links', find_links, '"pip=={arctasks.deploy.provision.pip.version}"'),
        (pip, 'install --find-links', find_links, '--cache-dir {remote.pip.download_cache} wheel'),
    ), many=True)


@arctask(configured='stage', timed=True)
def deploy(ctx, provision=True, overwrite=False, static=True, build_static=True,
           remove_distributions=None, wheels=True, install=True, copy_settings=True,
           copy_wsgi_module=True, migrate=False, link=True):
    """Deploy a new version.

    The default directory structure on the server looks like this::

        /vol/www/{package}/
            {env}                 # Symlink pointing at active build in builds/{env}/
            builds/{env}/         # Builds for env (stage, prod)
                {version}/        # Current build root
                    .env/         # Virtualenv directory
                    wsgi/wsgi.py  # WSGI entry point [1]
                    media         # Symlink to media/{env} [2]
                    static        # Symlink to static/{env} [2]
            pip/download-cache/   # Cached package downloads
            pip/wheelhouse/       # Cached package builds
            media/{env}/          # Media files for env (shared across builds)
            static/{env}/         # Static files for env (shared across builds)

    [1] Use {package}/wsgi.py for legacy builds.
    [2] Only necessary for legacy Apache config; only created when the
        ``--old-style`` flag is passed to the :func:`.link` task.

    """
    try:
        result = remote(
            ctx, 'readlink {remote.path.env}', echo=False, hide=True, abort_on_failure=False)
        active_path = result.stdout.strip()

        print_header(
            'Preparing to deploy {name} to {env} ({arctasks.runners.remote.host})'.format(**ctx))
        if active_path:
            active_version = posixpath.basename(active_path)
            print_error('Active version: {} ({})'.format(active_version, active_path))
        else:
            print_warning('There is no active version')
        print_success('New version: {version} ({remote.build.dir})'.format(**ctx))
        print_info('Configuration:')
        show_config(ctx, tasks=False, initial_level=1)
        print_warning('\nPlease review the configuration above.')

        if not migrate:
            print_warning('\nNOTE: Migrations are not run by default; pass --migrate to run them\n')

        if confirm(ctx, 'Continue with deployment of version {version} to {env}?'):
            # For access to tasks that are shadowed by args.
            tasks = globals()

            # Do all local pre-processing stuff up here

            build_dir = ctx.path.build.root
            if os.path.isdir(build_dir):
                shutil.rmtree(build_dir)
            os.makedirs(build_dir)

            if static and build_static:
                tasks['build_static'](ctx)

            # Do remote stuff down here

            if provision:
                tasks['provision'](ctx, overwrite)

            # Push stuff
            push_app(ctx)
            if static:
                push_static(ctx)

            remove_distributions = [ctx.distribution] + as_list(remove_distributions)

            # Build & cache packages
            if wheels:
                for dist in remove_distributions:
                    remote(ctx, 'rm -f {remote.pip.wheel_dir}/%s*' % dist)
                result = remote(ctx, 'ls {remote.build.dist}')
                dists = result.stdout.strip().splitlines()
                for dist in dists:
                    if dist.startswith(ctx.distribution):
                        break
                else:
                    abort(1, 'Could not find source distribution for {distribution}'.format(**ctx))
                wheel(ctx, '{{remote.build.dist}}/{dist}'.format(dist=dist))

            if install:
                for dist in remove_distributions:
                    remote(ctx, ('{remote.build.pip} uninstall -y', dist), abort_on_failure=False)
                remote(ctx, (
                    '{remote.build.pip} install',
                    '--no-index',
                    '--find-links file://{remote.pip.wheel_dir}',
                    '--cache-dir {remote.pip.download_cache}',
                    '{distribution}',
                ))

            copy_file(
                ctx, abs_path(ctx.remote.build.manage_template, format_kwargs=ctx),
                ctx.remote.build.manage, template=True, mode='ug+rwx,o-rwx')

            if copy_settings:
                copy_file(ctx, 'local.base.cfg', '{remote.build.dir}')
                copy_file(ctx, '{local_settings_file}', '{remote.build.local_settings_file}')

            if copy_wsgi_module:
                copy_file(ctx, '{package}/wsgi.py', '{remote.build.wsgi_dir}')

            if migrate:
                remote_manage(ctx, 'migrate')

            if link:
                tasks['link'](ctx, ctx.version)
                restart(ctx)

            # Permissions are updated after restarting because this
            # could take a while. A screen session is used to run the
            # chmod command because we don't want to sit around waiting,
            # and we assume the chmod will succeed.
            remote(ctx, (
                'screen -d -m',
                'chmod -R ug=rwX,o-rwx {remote.build.dir} {remote.path.static}'
            ))
        else:
            abort(message='Deployment aborted')

    except KeyboardInterrupt:
        abort(message='\nDeployment aborted')


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
        cmd = [('test -d', d) for d in build_dirs]
        result = remote(ctx, cmd, many='&&', echo=False, abort_on_failure=False)
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
        dirs = remote(ctx, (
            'find', build_root, '-mindepth 1 -maxdepth 1 -type d'
        ), cd='/', echo=False, hide='stdout')
        result = dirs.stdout.strip().splitlines()
        if result:
            dirs = ' '.join(result)
            result = remote(
                ctx, 'stat -c "%n %Y" {dirs}'.format(dirs=dirs), echo=False, hide=True)
            data = result.stdout.strip().splitlines()
            data = [d.split(' ', 1) for d in data]
            data = [
                (d[0], posixpath.basename(d[0]), datetime.fromtimestamp(int(d[1])))
                for d in data
            ]
            data = sorted(data, key=lambda item: item[1], reverse=True)
            longest = max(len(d[1]) for d in data) + 1
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
        abort(1, 'You have to keep at least the latest version')

    result = remote(ctx, 'readlink {remote.path.env}', hide='stdout')
    active_path = result.stdout.strip()
    active_version = posixpath.basename(active_path)

    print_info('All {env} builds; newest first:'.format(**ctx))
    remote(ctx, 'ls -clt {remote.build.root}')

    result = remote(ctx, 'ls -c {remote.build.root}', hide='stdout')
    versions = result.stdout.strip().splitlines()
    versions_to_keep = versions[:keep]
    versions_to_remove = versions[keep:]
    if active_version in versions_to_remove:
        versions_to_remove.remove(active_version)
    if versions_to_keep:
        print_success('Versions that will be kept:')
        print(', '.join(versions_to_keep))
    if versions_to_remove:
        versions_to_remove_str = ', '.join(versions_to_remove)
        print_danger('Versions that will be removed:')
        print(versions_to_remove_str)
        if confirm(ctx, 'Really remove these versions?', yes_values=('really',)):
            print_danger('Removing {0}...'.format(versions_to_remove_str))
            remote(ctx, (
                'rm -r',
                '%s/{%s}' % (ctx.remote.build.root, ','.join(versions_to_remove)),
            ), echo=True, inject_context=False)
    else:
        print_warning('No versions to remove')

    print_info('Remaining {env} builds; newest first:'.format(**ctx))
    remote(ctx, 'ls -clt {remote.build.root}')


@arctask(configured=True)
def link(ctx, version, old_style=None):
    build_dir = '{remote.build.root}/{v}'.format(v=version, **ctx)
    remote(ctx, ('ln', '-sfn', build_dir, '{remote.path.root}/{env}'))

    # Link the specified version's static manifest
    remote(ctx, 'ln -sf {remote.build.dir}/staticfiles.json {remote.path.static}/staticfiles.json')

    # XXX: This supports old-style deployments where the media and
    #      static directories are in the source directory.
    if old_style:
        media_dir = '{build_dir}/media'.format(build_dir=build_dir)
        static_dir = '{build_dir}/static'.format(build_dir=build_dir)
        remote(ctx, ('ln -sfn /vol/www/{package}/media/{env}', media_dir))
        remote(ctx, ('ln -sfn /vol/www/{package}/static/{env}', static_dir))


@arctask(configured=True)
def push_app(ctx, deps=None):
    sdist = 'setup.py sdist -d {path.build.dist}'
    local(ctx, (sys.executable, sdist), hide='stdout')
    for path in as_list(deps):
        local(ctx, (sys.executable, sdist), hide='stdout', cd=path)
    remote(ctx, 'rm -f {remote.build.dist}/*')
    rsync(ctx, '{path.build.dist}/*', '{remote.build.dist}')


@arctask(build_static, configured=True)
def push_static(ctx, delete=False):
    settings = django.get_settings()
    static_root = '{0.STATIC_ROOT}{1}'.format(settings, os.sep)
    rsync(ctx, static_root, ctx.remote.path.static, delete=delete)
    manifest = os.path.join(settings.STATIC_ROOT, 'staticfiles.json')
    if os.path.isfile(manifest):
        copy_file(ctx, manifest, ctx.remote.build.dir)


@arctask(configured=True)
def wheel(ctx, distribution):
    remote(ctx, (
        '{remote.build.pip} wheel',
        '--wheel-dir {remote.pip.wheel_dir}',
        '--cache-dir {remote.pip.download_cache}',
        '--find-links file://{remote.build.dir}/dist',
        '--find-links file://{remote.pip.wheel_dir}',
        '--find-links {remote.pip.find_links}',
        distribution,
    ))


@arctask(configured=True)
def restart(ctx, get=None, scheme=None):
    settings = django.get_settings()
    remote(ctx, 'touch {remote.build.wsgi_dir}/wsgi.py')
    if get:
        print_info('Getting {0.DOMAIN_NAME}...'.format(settings))
        urlretrieve('{scheme}://{0.DOMAIN_NAME}/'.format(settings, scheme=scheme), os.devnull)
