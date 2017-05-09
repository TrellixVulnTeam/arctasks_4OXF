import os
import posixpath

import boto3

from runcommands import command
from runcommands.commands import local, remote
from runcommands.util import abort, printer

from arctasks.static import build_static
from arctasks.remote import copy_file, rsync

from .provision import provision


__all__ = [
    'deploy',
    'local',
    'remote',
    'push_static',
    'push_nginx_config',
    'restart_nginx',
    'push_uwsgi_config',
    'restart_uwsgi',
    'restart_uwsgi_emperor',
]


@command(env=True)
def deploy(config, version=None, provision_=False, create_cert=False, overwrite=False,
           overwrite_venv=False, install=True, static=True, link=True, restart_uwsgi_=False,
           restart_nginx_=False, restart_all=False):
    if version:
        config = config.copy(version=version)
    elif config.get('version'):
        printer.info('Using default version:', config.version)
    else:
        abort(1, 'Version must be specified via config or passed as an option')

    restart_uwsgi_ = restart_uwsgi_ or restart_all
    restart_nginx_ = restart_nginx_ or restart_all

    if provision_:
        provision(config, create_cert=create_cert)
    else:
        printer.info('Skipped provisioning')

    # Create directory for this version
    deploy_dir_exists = remote(config, 'test -d {deploy.dir}', abort_on_failure=False)

    if deploy_dir_exists and overwrite:
        remote(config, 'rm -r {deploy.dir}')
        deploy_dir_exists = False

    if not deploy_dir_exists:
        remote(config, 'mkdir -p {deploy.dir}')

    # Create virtualenv for this version
    venv_exists = remote(config, 'test -d {deploy.venv}', abort_on_failure=False)

    if venv_exists and overwrite_venv:
        remote(config, 'rm -r {deploy.venv}')
        venv_exists = False

    if not venv_exists:
        remote(config, (
            '/usr/bin/virtualenv-{python.version}',
            '-p /usr/bin/python{python.version}',
            '{deploy.venv}',
        ))
        remote(config, '{deploy.pip.exe} install --upgrade pip')

    # Upload application source
    # TODO: Build a source dist and upload that instead
    excludes = ('build/', 'media/', 'static/', 'local.cfg', '*.egg-info/')
    rsync(config, './', '{deploy.src}', excludes=excludes, delete=True, hide='stdout')

    # Copy additional files. Files with no destination are copied to
    # {deploy.dir}. Files with a relative destination path are copied to
    # {deploy.dir}/{destination}. Files that end with ".template" will
    # be copied as templates (i.e., config values will be injected).
    for source, destination in config.deploy.copy_files.items():
        source = source.format(**config)
        destination = destination.format(**config)
        deploy_dir = config.deploy.dir

        source_base_name, ext = os.path.splitext(os.path.basename(source))
        template = ext == '.template'

        if destination:
            if not posixpath.isabs(destination):
                destination = posixpath.join(deploy_dir, destination)
        else:
            destination = deploy_dir
            if template:
                destination = posixpath.join(destination, source_base_name)

        copy_file(config, source, destination, template=template)

    remote(config, 'ln -sfn {local_settings_file} local.cfg', cd='{deploy.dir}')

    if static:
        # Build and upload static files
        push_static(config, build=True, hide='stdout')

    # Build source
    if install:
        find_links = tuple(('--find-links', link) for link in config.deploy.pip.find_links)
        remote(config, (
            '{deploy.pip.exe}',
            'install',
            find_links,
            '--cache-dir {deploy.pip.cache_dir}',
            '--disable-pip-version-check',
            'https://github.com/PSU-OIT-ARC/arctasks/archive/master.tar.gz',
            '{deploy.src}',
        ))

    # Make this version the current version
    if link:
        remote(config, 'ln -sfn {deploy.dir} {deploy.link}')
        if static:
            remote(config, 'ln -sfn {deploy.dir}/staticfiles.json', cd='{deploy.static_dir}')

    # Set permissions
    remote(config, 'chmod -R ug=rwX,o=rX {deploy.root}')

    # Copying the uWSGI config file will cause the app's uWSGI process
    # to restart automatically.
    if restart_uwsgi_:
        push_uwsgi_config(config)
        restart_uwsgi(config)

    if restart_nginx_:
        push_nginx_config(config)
        restart_nginx(config)


@command(env=True)
def push_static(config, build=True, static_root='{build.static_root}',
                destination='{deploy.static_dir}', dry_run=False, delete=False, echo=False,
                hide=False):
    if build:
        build_static(config, static_root=static_root)

    # Ensure directory ends with path separator.
    static_root = os.path.join(static_root, '')

    # local(config, (
    #     'aws s3 sync',
    #     '--acl public-read',
    #     '--dryrun' if dry_run else '',
    #     static_root,
    #     destination,
    # ), echo=echo, hide=hide)

    rsync(
        config, static_root, destination, excludes=['staticfiles.json'],
        dry_run=dry_run, delete=delete, echo=echo, hide=hide)

    # Copy the static files manifest to the deployment directory; it
    # will be linked later.
    manifest = os.path.join(static_root, 'staticfiles.json')
    if os.path.isfile(manifest):
        copy_file(config, manifest, config.deploy.dir)


@command(env=True)
def push_uwsgi_config(config):
    template = '{deploy.uwsgi.config_file}'
    destination = '/etc/uwsgi/{package}.ini'
    copy_file(config, template, destination, sudo=True, template=True)


@command(env=True)
def restart_uwsgi(config):
    """Restart the app's uWSGI process."""
    remote(config, 'touch /etc/uwsgi/{package}.ini', sudo=True)


@command(env=True)
def restart_uwsgi_emperor(config):
    """Restart the uWSGI Emperor process.

    .. note:: This generally shouldn't (need to) be done.

    """
    remote(config, 'restart uwsgi', sudo=True)


@command(env=True)
def push_nginx_config(config):
    copy_file(
        config, 'etc/nginx/conf.d/nginx.conf', '/etc/nginx/conf.d/{package}.conf',
        sudo=True, template=True, template_type='string')


@command(env=True)
def restart_nginx(config):
    remote(config, 'service nginx restart', sudo=True)
