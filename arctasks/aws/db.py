from runcommands import command
from runcommands.config import Config
from runcommands.commands import remote
from runcommands.util import abort, confirm


@command(
    env=True,
    config={
        'defaults.runcommands.runners.commands.remote.cd': '/',
        'defaults.runcommands.runners.commands.remote.run_as': None,
        'defaults.runcommands.runners.commands.remote.sudo': True,
    }
)
def createdb_aws(config, type=None, user='{db.user}', host='{db.host}', port='{db.port}',
                 name='{db.name}', drop=False, with_postgis=False, extensions=()):
    if type is None:
        type = config.db.type
    args = (config, user, host, port, name, drop)
    if type == 'mysql':
        creator = create_mysql_db
    elif type == 'postgresql':
        args += (with_postgis, extensions)
        creator = create_postgresql_db
    else:
        raise ValueError('Unknown database type: {db.type}'.format_map(config))
    creator(*args)


def create_postgresql_db(config, user='{db.user}', host='{db.host}', port='{db.port}',
                         name='{db.name}', drop=False, with_postgis=False, extensions=()):
    """Create a PostgreSQL database with the specified ``name``.

    This also creates the user specified by ``user`` as a superuser
    with no password. This is insecure and should only be used in
    development and testing.

    The --with-postgis flag can be used to spatially-enable the
    database. This only works with PostgreSQL 9.1+ and PostGIS 2.0+.

    """
    remote(config, ('yum', 'install', '-y', 'postgresql95'))

    if with_postgis and 'postgis' not in extensions:
        extensions = ['postgis'] + list(extensions)

    def run_command(*command, database='postgres'):
        command = ' '.join(command)
        command = '"{command}"'.format(command=command)
        remote(config, (
            'psql',
            '-U', user,
            '-h', host,
            '-p', port,
            '-d', database,
            '-c', command,
        ), abort_on_failure=False)

    if drop:
        run_command('DROP DATABASE', name) if drop else None

    run_command('CREATE DATABASE', name, 'WITH OWNER', user)

    for extension in extensions:
        run_command('CREATE EXTENSION', extension, database=name)


def create_mysql_db(config, user='{db.user}', host='{db.host}', port='{db.port}',
                    name='{db.name}', drop=False):
    """Create a MySQL database with the specified ``name``.

    This also creates the user specified by ``user`` as a superuser
    with no password. This is insecure and should only be used in
    development and testing.

    """
    remote(config, ('yum', 'install', '-y', 'mysql56'))

    def run_command(*command):
        command = ' '.join(command)
        command = '"{command}"'.format(command=command)
        remote(config, (
            'mysql',
            '-h', host,
            '-p', port,
            '-u', 'root',
            '-e', command,
        ), abort_on_failure=False)

    f = locals()

    if drop:
        run_command('DROP DATABASE', name)

    run_command('CREATE DATABASE', name)
