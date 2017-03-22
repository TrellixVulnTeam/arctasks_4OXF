from runcommands import command
from runcommands.commands import remote

from arctasks.remote import copy_file


__all__ = [
    'provision',
]


@command(config={
    'defaults.arctasks.remote.copy_file.run_as': None,
    'defaults.arctasks.remote.copy_file.sudo': True,
    'defaults.arctasks.remote.rsync.run_as': None,
    'defaults.arctasks.remote.rsync.sudo': True,
    'defaults.runcommands.runners.commands.remote.run_as': None,
    'defaults.runcommands.runners.commands.remote.sudo': True,
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


