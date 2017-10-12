import posixpath

from runcommands import bool_or, command
from runcommands.commands import remote
from runcommands.util import confirm, printer

from arctasks.remote import copy_file


__all__ = [
    'provision_volume',
    'provision_common',
    'provision_webhost',
    'install_certbot',
    'make_cert',
]


GIS_PACKAGES = ('binutils', 'gdal', 'proj')
EFS_MOUNT_OPTIONS = "nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2"


def _add_device_mount(config, device, filesystem, mount_point, mount_options):
    result = remote(config, ('grep', device, '/etc/fstab'), abort_on_failure=False)
    if result.failed:
        fstab_entry = "{}\t{}\t{}\t{}".format(device, mount_point, filesystem, mount_options)
        remote(config, 'echo "{}" >> /etc/fstab'.format(fstab_entry))
    remote(config, ('mkdir', '-p', mount_point))
    result = remote(config, ('mount', '|', 'grep', mount_point), abort_on_failure=False)
    if result.failed:
        remote(config, ('mount', mount_point))


def provision_volume(config, device='/dev/sdk', filesystem='ext4',
                     mount_point='/vol/local', mount_options="defaults"):
    prompt = "Create {} filesystem on '{}'?".format(filesystem, device)
    if confirm(config, prompt, color='error'):
        remote(config, ('mkfs.{}'.format(filesystem), device))

    _add_device_mount(config, device, filesystem, mount_point, mount_options)


def provision_common(config, timezone):
    timezone_path = posixpath.join('/usr/share/zoneinfo', timezone)
    remote(config, ('ln -sf', timezone_path, '/etc/localtime'))

    # Create service user for deployments
    remote(config, (
        'id {service.user} ||',
        '(mkdir -p {remote.deploy_root} &&',
        'adduser --home-dir {remote.path.root} {service.user} --user-group)'
    ))

    # Enable package installation from EPEL
    remote(config, 'yum-config-manager --enable epel')

    # Upgrade system packages
    remote(config, 'yum update -y')
    remote(config, 'yum upgrade -y')

    # Configure support for EFS
    # Install NFS utilities
    remote(config, 'yum install -y nfs-utils')
    # Configure EFS mount
    if config.infrastructure.efs.fsid:
        device = "{}.efs.{}.amazonaws.com:/".format(config.infrastructure.efs.fsid,
                                                    config.infrastructure.region)
        mount_point = config.infrastructure.efs.mount_point
        _add_device_mount(config, device, 'nfs4', mount_point, EFS_MOUNT_OPTIONS)


@command(
    env=True,
    config={
        'defaults.arctasks.remote.copy_file.run_as': None,
        'defaults.arctasks.remote.copy_file.sudo': True,
        'defaults.runcommands.runners.commands.remote.cd': '/',
        'defaults.runcommands.runners.commands.remote.run_as': None,
        'defaults.runcommands.runners.commands.remote.sudo': True,
    },
    type={
        'with_uwsgi': bool_or(str),
    }
)
def provision_webhost(config, create_cert=False, timezone='America/Los_Angeles', packages=('nginx',),
                      additional_packages=(), with_python='{python.version}', with_uwsgi='latest',
                      with_gis=False):
    """Provision an existing EC2 instance.

    - Installs Nginx, Python, and uWSGI by default
    - Creates /deploy as root directory for deployments
    - Creates deploy user to own /deploy and its contents
    - Adds an SSL certificate when ``--create_cert`` flag is passed (via
      Let's Encrypt)

    """
    # Perform common provision tasks
    provision_common(config, timezone)

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
        copy_file(config, '{remote.uwsgi.init_file}', '/etc/init/uwsgi.conf')
        remote(config, 'initctl start uwsgi || echo "uwsgi already running"')

    if with_gis:
        # Install and configure GIS dependencies
        remote(config, ('yum install -y', GIS_PACKAGES))

    if create_cert:
        install_certbot(config)
        make_cert(config.domain_name)

    if 'nginx' in packages:
        # Install nginx app configuration
        template = '{remote.nginx.config_file}'
        destination = '/etc/nginx/conf.d/{package}.conf'
        copy_file(config, template, destination, template=True)
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
        'mkdir -p {remote.path.root} &&',
        'chown {service.user}:{service.user} {remote.path.root} &&'
        'chmod 771 {remote.path.root}',
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
