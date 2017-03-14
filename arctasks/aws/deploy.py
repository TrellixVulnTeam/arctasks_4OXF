from taskrunner import task
from taskrunner.tasks import local, remote, show_config  # noqa
from taskrunner.util import abort, printer

from arctasks.remote import copy_file, rsync


__all__ = [
    'deploy',
    'local',
    'remote',
    'provision',
    'push_nginx_config',
    'restart_nginx',
    'restart_uwsgi',
    'restart_uwsgi_emperor',
]


@task(config={
    'defaults.arctasks.remote.copy_file.run_as': None,
    'defaults.arctasks.remote.copy_file.sudo': True,
    'defaults.arctasks.remote.rsync.run_as': None,
    'defaults.arctasks.remote.rsync.sudo': True,
    'defaults.taskrunner.runners.tasks.remote.run_as': None,
    'defaults.taskrunner.runners.tasks.remote.sudo': True,
})
def provision(config, create_cert=False):
    """Provision an existing EC2 instance.

    - Installs Nginx, Python 3.5, and uWSGI
    - Creates /deploy as root directory for deployments
    - Creates deploy user to own /deploy and its contents
    - Adds an SSL certificate when ``create_cert=True`` (via Let's
      Encrypt)

    """
    # Create service user for deployments
    remote(config, (
        'id {deploy.user} ||',
        'adduser --home-dir {deploy.root} {deploy.user} --user-group'
    ))

    # Upgrade system packages
    remote(config, 'yum update -y')

    # Install system packages
    remote(config, (
        'yum install -y',
        'nginx',
        'python35',
        'python35-devel',
        'python35-pip',
        'python35-virtualenv',
    ))

    # Install and configure uWSGI
    remote(config, '/usr/bin/pip-3.5 install uwsgi')
    remote(config, 'mkdir -p /etc/uwsgi /var/log/uwsgi /var/run/uwsgi')
    copy_file(config, '{deploy.uwsgi.init_file}', '/etc/init/uwsgi.conf')

    # Install Let's Encrypt
    remote(config, (
        'curl -O https://dl.eff.org/certbot-auto &&',
        'chmod +x certbot-auto',
    ), cd='/usr/local/bin')

    if create_cert:
        remote(config, 'mkdir -p /etc/pki/nginx')
        remote(config, (
            'test -f /etc/pki/nginx/{domain_name}.pem ||',
            'openssl dhparam -out /etc/pki/nginx/{domain_name}.pem 2048',
        ))
        remote(config, (
            '/usr/local/bin/certbot-auto --debug --non-interactive',
            'certonly',
            '--agree-tos',
            '--domain {domain_name}'
            '--email {letsencrypt.email}',
            '--standalone',
        ))

    # Start web server now and make sure it starts on boot
    remote(config, 'service nginx start && chkconfig nginx on')

    # Create root directory for deployments
    remote(config, (
        'mkdir -p {deploy.root} &&',
        'chown {deploy.user}:{deploy.user} {deploy.root} &&'
        'chmod 771 {deploy.root}',
    ))


@task
def deploy(config, version=None, provision_=False, create_cert=False, overwrite=False,
           overwrite_venv=False, restart_uwsgi_=False, restart_nginx_=False):
    if version:
        config = config._clone(version=version)
    elif config.get('version'):
        printer.info('Using default version:', config.version)
    else:
        abort(1, 'Version must be specified via config or passed as an option')

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
        remote(config, '/usr/bin/virtualenv-3.5 -p /usr/bin/python3.5 {deploy.venv}')
        remote(config, '{deploy.pip.exe} install --upgrade pip')

    # Upload application source
    # TODO: Build a source dist and upload that instead
    rsync(config, './', '{deploy.src}')

    # Copy additional files. Files with no destination are copied to
    # {deploy.dir}. Files with a relative destination path are copied to
    # {deploy.dir}/{destination}.
    for source, destination in config.deploy.copy_files.items():
        if destination:
            if not destination.format(**config).startswith('/'):
                destination = '/'.join(('{deploy.dir}', destination))
        else:
            destination = '{deploy.dir}'
        copy_file(config, source, destination)

    # Build source
    find_links = tuple(('--find-links', link) for link in config.deploy.pip.find_links)
    remote(config, (
        '{deploy.pip.exe}',
        'install',
        find_links,
        '--cache-dir {deploy.pip.cache_dir}',
        '--disable-pip-version-check',
        '{deploy.src}',
    ))

    # Set permissions
    remote(config, 'chmod -R ug=rwX,o=rX {deploy.root}')

    # Make this version the current version
    remote(config, 'ln -sfn {deploy.dir} {deploy.link}')

    # Copying the uWSGI config file will cause the app's uWSGI process
    # to restart automatically.
    if restart_uwsgi_:
        template = '{deploy.uwsgi.config_file}'
        destination = '/etc/uwsgi/{package}.ini'
        copy_file(config, template, destination, sudo=True, template=True)

    if restart_nginx_:
        push_nginx_config(config)
        restart_nginx(config)


@task
def restart_uwsgi(config):
    """Restart the app's uWSGI process."""
    remote(config, 'touch /etc/uwsgi/{package}.ini', sudo=True)


@task
def restart_uwsgi_emperor(config):
    """Restart the uWSGI Emperor process.

    .. note:: This generally shouldn't (need to) be done.

    """
    remote(config, 'restart uwsgi', sudo=True)


@task
def push_nginx_config(config):
    copy_file(config, 'etc/nginx/conf.d/nginx.conf', '/etc/nginx/conf.d/{package}.conf', sudo=True)


@task
def restart_nginx(config):
    remote(config, 'service nginx restart', sudo=True)
