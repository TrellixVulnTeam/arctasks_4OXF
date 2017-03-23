import posixpath

import boto3
import botocore.exceptions

from runcommands import command
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
]


DEFAULT_REGION = 'us-west-2'


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


@command
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


@command
def create_instance(config, region=DEFAULT_REGION, image='ami-f173cc91', type_='t2.micro', min_=1,
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


@command
def start_instance(config, id_, region=DEFAULT_REGION, dry_run=False):
    """Start EC2 instance."""
    client = make_client(region)
    instance = get_instance(id_, abort=True)
    printer.success('Starting instance {instance.id}...'.format_map(locals()))
    try_dry_run(instance.start, DryRun=dry_run)
    if dry_run:
        printer.success('[DRY RUN]', end=' ')
    printer.success('Instance started')


@command
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


@command
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


@command
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


@command(config={
    'defaults.arctasks.remote.copy_file.run_as': None,
    'defaults.arctasks.remote.copy_file.sudo': True,
    'defaults.arctasks.remote.rsync.run_as': None,
    'defaults.arctasks.remote.rsync.sudo': True,
    'defaults.runcommands.runners.commands.remote.run_as': None,
    'defaults.runcommands.runners.commands.remote.sudo': True,
})
def provision(config, create_cert=False, timezone='America/Los_Angeles'):
    """Provision an existing EC2 instance.

    - Installs Nginx, Python 3.5, and uWSGI
    - Creates /deploy as root directory for deployments
    - Creates deploy user to own /deploy and its contents
    - Adds an SSL certificate when ``create_cert=True`` (via Let's
      Encrypt)

    """
    timezone_path = posixpath.join('/usr/share/zoneinfo', timezone)
    remote(config, ('ln -sf', timezone_path, '/etc/localtime'))

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


