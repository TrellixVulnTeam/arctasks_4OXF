import posixpath

import boto3
import botocore.exceptions

from runcommands import bool_or, command
from runcommands.commands import remote
from runcommands.util import confirm, printer

from arctasks.remote import copy_file


__all__ = [
    'provision',
    'install_certbot',
    'make_cert',
]



@command(
    env=True,
    config={
        'defaults.arctasks.remote.copy_file.run_as': None,
        'defaults.arctasks.remote.copy_file.sudo': True,
        'defaults.arctasks.remote.rsync.run_as': None,
        'defaults.arctasks.remote.rsync.sudo': True,
        'defaults.runcommands.runners.commands.remote.run_as': None,
        'defaults.runcommands.runners.commands.remote.sudo': True,
    },
    type={
        'with_uwsgi': bool_or(str),
    }
)
def provision(config, create_cert=False, timezone='America/Los_Angeles', packages=('nginx',),
              additional_packages=(), with_python='{python.version}', with_uwsgi='latest'):
    """Provision an existing EC2 instance.

    - Installs Nginx, Python, and uWSGI by default
    - Creates /deploy as root directory for deployments
    - Creates deploy user to own /deploy and its contents
    - Adds an SSL certificate when ``--create_cert`` flag is passed (via
      Let's Encrypt)

    """
    timezone_path = posixpath.join('/usr/share/zoneinfo', timezone)
    remote(config, ('ln -sf', timezone_path, '/etc/localtime'))

    # Create service user for deployments
    remote(config, (
        'id {deploy.user} ||',
        'adduser --home-dir {deploy.root} {deploy.user} --user-group'
    ))

    # Upgrade system packages
    remote(config, 'yum update -y', timeout=120)

    # Install other packages
    packages = list(packages)
    packages.extend(additional_packages)

    if with_python or with_uwsgi:
        v = with_python.format_map(config).replace('.', '')
        python_packages = [
            'python{v}',
            'python{v}-devel',
            'python{v}-pip',
            'python{v}-virtualenv',
        ]
        python_packages = [p.format(v=v) for p in python_packages]
        packages.extend(python_packages)
        pip = '/usr/bin/pip-{v}'.format(v=with_python)

    if with_uwsgi:
        packages.append('gcc')

    # Install system packages
    remote(config, ('yum install -y', packages), timeout=120)

    if with_uwsgi:
        # Install and configure uWSGI
        uwsgi_version = '' if with_uwsgi in (True, 'latest') else with_uwsgi
        remote(config, (pip, 'install uwsgi', uwsgi_version))
        remote(config, 'mkdir -p /etc/uwsgi /var/log/uwsgi')
        copy_file(config, '{deploy.uwsgi.init_file}', '/etc/init/uwsgi.conf')

    if create_cert:
        install_certbot(config)
        make_cert(config.domain_name)

    if 'nginx' in packages:
        # Start web server now and make sure it starts on boot
        remote(config, 'service nginx start && chkconfig nginx on')
        if create_cert:
            remote(config, 'mkdir -p /etc/pki/nginx')
            remote(config, (
                'test -f /etc/pki/nginx/{domain_name}.pem ||',
                'openssl dhparam -out /etc/pki/nginx/{domain_name}.pem 2048',
            ))

    # Create root directory for deployments
    remote(config, (
        'mkdir -p {deploy.root} &&',
        'chown {deploy.user}:{deploy.user} {deploy.root} &&'
        'chmod 771 {deploy.root}',
    ))


@command(env=True)
def install_certbot(config):
    """Install Let's Encrypt client."""
    remote(config, (
        'curl -O https://dl.eff.org/certbot-auto &&',
        'chmod +x certbot-auto',
    ), cd='/usr/local/bin')


@command(env=True)
def make_cert(config, domain_name, email='webteam@pdx.edu'):
    """Create Let's encrypt certificate."""
    remote(config, (
        '/usr/local/bin/certbot-auto --debug --non-interactive',
        'certonly --agree-tos --standalone',
        '--domain', domain_name,
        '--email', email,
    ))
