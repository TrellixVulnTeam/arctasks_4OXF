import posixpath

import boto3
import botocore.exceptions

from runcommands import bool_or, command
from runcommands.commands import remote
from runcommands.util import confirm, printer

from arctasks.remote import copy_file


__all__ = [
    'list_instances',
    'create_instance',
    'start_instance',
    'stop_instance',
    'reboot_instance',
    'terminate_instance',
    'provision',
    'install_certbot',
    'make_cert',
]


DEFAULT_REGION = 'us-west-2'

# Amazon Linux AMI 2017.03.0 (HVM), SSD Volume Type
DEFAULT_AMI_ID = 'ami-8ca83fec'


def make_client(region=DEFAULT_REGION):
    client = boto3.resource('ec2', region_name=region)
    return client


def get_instance(id_, region=DEFAULT_REGION, abort=False):
    client = make_client(region)
    instances = client.instances.filter(Filters=[
        {'Name': 'instance-id', 'Values': [id_]},
    ])
    instances = list(instances)
    if len(instances) > 1:
        msg = 'Found multiple instances for ID: {id_}'.format_map(locals())
        if abort:
            abort(1, msg)
        raise ValueError(msg)
    return instances[0]


def try_dry_run(func, *args, **kwargs):
    try:
        dry_run = kwargs['DryRun']
    except KeyError:
        raise KeyError('DryRun keyword arg required') from None

    exc_raised = False

    try:
        result = func(*args, **kwargs)
    except botocore.exceptions.ClientError as exc:
        if dry_run and exc.response['Error'].get('Code') == 'DryRunOperation':
            result = kwargs.pop('_default', None)
            exc_raised = True
        else:
            raise

    if dry_run:
        assert exc_raised

    return result


@command(env=True)
def list_instances(config, region=DEFAULT_REGION, state='running'):
    """List instances (only running by default).

    To show all instances::

        show_instances --state '*'

    To show stopped instances:

        show_instances --state stopped

    """
    client = make_client(region)
    instances = client.instances.filter(Filters=[
        {'Name': 'instance-state-name', 'Values': [state]},
    ])
    for instance in instances:
        id_ = instance.id
        image_name = instance.image.name
        image_id = instance.image_id
        type_ = instance.instance_type
        launch_time = instance.launch_time.isoformat()
        template = '{id_} {image_name} {image_id} {type_} {launch_time}'
        printer.success(template.format_map(locals()))


@command(env=True)
def create_instance(config, region=DEFAULT_REGION, image=DEFAULT_AMI_ID, type_='t2.micro', min_=1,
                    max_=None, dry_run=False):
    """Create an EC2 instance."""
    max_ = min_ if max_ is None else max_
    client = make_client(region)
    instances = try_dry_run(
        client.create_instances,
        DryRun=dry_run,
        ImageId=image,
        InstanceType=type_,
        MinCount=min_,
        MaxCount=max_,
        _default=(),
    )
    for instance in instances:
        printer.success(
            'Created {instance.instance_type} instance with ID {instance.id}'
            .format_map(locals()))


@command(env=True)
def start_instance(config, id_, region=DEFAULT_REGION, dry_run=False):
    """Start EC2 instance."""
    client = make_client(region)
    instance = get_instance(id_, abort=True)
    printer.success('Starting instance {instance.id}...'.format_map(locals()))
    try_dry_run(instance.start, DryRun=dry_run)
    if dry_run:
        printer.success('[DRY RUN]', end=' ')
    printer.success('Instance started')


@command(env=True)
def stop_instance(config, id_, region=DEFAULT_REGION, dry_run=False):
    """Stop EC2 instance."""
    client = make_client(region)
    instance = get_instance(id_, abort=True)
    msg = 'Stop instance {instance.id}?'.format_map(locals())
    if confirm(config, msg):
        printer.warning('Stopping instance {instance.id}...'.format_map(locals()))
        try_dry_run(instance.stop, DryRun=dry_run)
        if dry_run:
            printer.warning('[DRY RUN]', end=' ')
        printer.warning('Instance stopped')


@command(env=True)
def reboot_instance(config, id_, region=DEFAULT_REGION, dry_run=False):
    """Reboot EC2 instance."""
    client = make_client(region)
    instance = get_instance(id_, abort=True)
    msg = 'Reboot instance {instance.id}?'.format_map(locals())
    if confirm(config, msg):
        printer.warning('Rebooting instance {instance.id}...'.format_map(locals()))
        try_dry_run(instance.reboot, DryRun=dry_run)
        if dry_run:
            printer.warning('[DRY RUN]', end=' ')
        printer.warning('Instance rebooted')


@command(env=True)
def terminate_instance(config, id_, region=DEFAULT_REGION, dry_run=False):
    """Terminate EC2 instance."""
    client = make_client(region)
    instance = get_instance(id_, abort=True)
    msg = 'Terminate instance {instance.id}?'.format_map(locals())
    if confirm(config, msg, color='danger', yes_values=['yes']):
        printer.danger('Terminating instance {instance.id}...'.format_map(locals()))
        try_dry_run(instance.terminate, DryRun=dry_run)
        if dry_run:
            printer.danger('[DRY RUN]', end=' ')
        printer.danger('Instance terminated')


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
