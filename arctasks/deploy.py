import os
import posixpath
import shutil
import sys
from urllib.request import urlretrieve

from invoke.tasks import ctask as task

from .config import configured, show_config
from .remote import manage as remote_manage, rsync, copy_file
from .runners import local, remote
from .static import build_static
from .util import abort, confirm, print_header, print_info, print_warning, print_error


@task(configured)
def provision(ctx, overwrite=False):
    build_dir = ctx.remote.build.dir
    venv = ctx.remote.build.venv
    if overwrite:
        # Remove existing build directory if present
        remote(ctx, ('rm -rf', build_dir, venv))
    # Make build dir
    remote(
        ctx, 'mkdir -p {remote.build.dir} {remote.build.dist} {remote.build.wsgi} -m ug=rwx,o-rwx')
    # Create virtualenv for build
    result = remote(ctx, ('test -d', venv), abort_on_failure=False)
    if result.failed:
        remote(ctx, ('virtualenv -p python3', venv))
    # Provision virtualenv with basics
    pip = ctx.remote.build.pip
    find_links = ctx.remote.pip.find_links
    remote(ctx, (
        (pip, 'install -U setuptools'),
        (pip, 'install --find-links', find_links, '"pip>={task.provision.pip.version}"'),
        (pip, 'install --find-links', find_links, '--cache-dir {remote.pip.download_cache} wheel'),
    ), cd=build_dir, many=True)


@task(configured)
def deploy(ctx, provision=True, overwrite=False, static=True, wheels=True, install=True,
           copy_settings=True, copy_wsgi_module=True, migrate=False, link=True):
    try:
        result = remote(
            ctx, 'readlink {remote.path.env}', cd=None, echo=False, hide=True,
            abort_on_failure=False)
        active_path = result.stdout.strip()

        print_header('Preparing to deploy {name} to {env}'.format(**ctx))
        print_info('New version: {version} ({remote.build.dir})'.format(**ctx))
        if active_path:
            active_version = posixpath.basename(active_path)
            print_info('Active version: {} ({})'.format(active_version, active_path))
        else:
            print_warning('There is no active version')
        print_info('Configuration:')
        show_config(ctx, tasks=False, initial_level=1)
        print_warning('\nPlease review the configuration above.')

        if confirm(ctx, 'Continue with deployment to {env}?'):
            # For access to tasks that are shadowed by args.
            tasks = globals()

            # Do all local pre-processing stuff up here

            build_dir = ctx.path.build.root
            if os.path.isdir(build_dir):
                shutil.rmtree(build_dir)
            os.makedirs(build_dir)

            if static:
                build_static(ctx)

            # Do remote stuff down here

            if provision:
                tasks['provision'](ctx, overwrite)

            # Push stuff
            push_app(ctx)
            if static:
                push_static(ctx)

            # Build & cache packages
            if wheels:
                remote(ctx, 'rm -f {remote.pip.wheel_dir}/{distribution}*')
                wheel(ctx, '{remote.build.dist}/{distribution}*')

            if install:
                remote(
                    ctx, '{remote.build.pip} uninstall -y {distribution}', abort_on_failure=False)
                remote(ctx, (
                    '{remote.build.pip} install',
                    '--no-index',
                    '--find-links file://{remote.pip.wheel_dir}',
                    '--cache-dir {remote.pip.download_cache}',
                    '{distribution}',
                ), cd='{remote.build.dir}')

            copy_file(ctx, '{remote.build.manage_template}', '{remote.build.manage}', template=True,
                mode='ug+rwx,o-rwx')

            if copy_settings:
                copy_file(ctx, 'local.base.cfg', '{remote.build.dir}')
                copy_file(ctx, '{local_settings_file}', '{remote.build.dir}/local.cfg')

            if copy_wsgi_module:
                copy_file(ctx, '{package}/wsgi.py', '{remote.build.wsgi}')

            if migrate:
                remote_manage(ctx, 'migrate')

            if link:
                tasks['link'](ctx, ctx.version)
                restart(ctx)

            # Permissions are updated after restarting because this could take a *long* time
            remote(ctx, 'chmod -R ug=rwX,o-rwx {remote.path.root}/* {remote.path.root}/.??*')
        else:
            abort(message='Deployment aborted')

    except KeyboardInterrupt:
        abort(message='\nDeployment aborted')


@task(configured, help={'rm': 'Remove the specified build', 'yes': 'Skip confirmations'})
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
        version = rm
        build_dir = '{build_root}/{version}'.format(**locals())
        result = remote(ctx, ('test -d', build_dir), echo=False, abort_on_failure=False)
        if result.failed:
            print_error('Build directory', build_dir, 'does not exist')
        else:
            prompt = 'Really delete build {version} at {build_dir}?'.format(**locals())
            if yes or confirm(ctx, prompt):
                remote(ctx, ('rm -r', build_dir))
    else:
        print_header('Builds:')
        remote(ctx, ('stat -c "%n %y" *', 'sort -k2,3'), cd=build_root, echo=False, many='|')


@task(configured)
def link(ctx, version):
    build_dir = '{remote.build.root}/{v}'.format(v=version, **ctx)
    remote(ctx, ('ln', '-sfn', build_dir, '{env}'), cd='{remote.path.root}')


@task(configured)
def push_app(ctx):
    local(ctx, (sys.executable, 'setup.py sdist -d {path.build.dist}'), hide='stdout')
    remote(ctx, 'rm -f {remote.build.dist}/{package}*')
    copy_file(ctx, '{path.build.dist}/{distribution}*', '{remote.build.dist}')


@task(configured, build_static)
def push_static(ctx, delete=False):
    from django.conf import settings
    rsync(ctx, '{0.STATIC_ROOT}/'.format(settings), ctx.remote.path.static, delete=delete)


@task(configured)
def wheel(ctx, distribution):
    remote(ctx, (
        '{remote.build.pip} wheel',
        '--wheel-dir {remote.pip.wheel_dir}',
        '--cache-dir {remote.pip.download_cache}',
        '--find-links file://{remote.build.dir}/dist',
        '--find-links file://{remote.pip.wheel_dir}',
        '--find-links {remote.pip.find_links}',
        distribution,
    ), path='/usr/pgsql-9.3/bin', cd='{remote.build.dir}')


@task(configured)
def restart(ctx):
    from django.conf import settings
    remote(ctx, 'touch {remote.build.wsgi}/wsgi.py', cd=None)
    print_info('Getting {0.DOMAIN_NAME}...'.format(settings))
    urlretrieve('http://{0.DOMAIN_NAME}/'.format(settings), os.devnull)
