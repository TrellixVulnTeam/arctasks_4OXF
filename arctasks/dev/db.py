import os
from getpass import getpass
from tempfile import mkstemp

from runcommands import command
from runcommands.config import Config
from runcommands.commands import local
from runcommands.util import abort, confirm


@command(default_env='dev')
def createdb(config, type=None, user='{db.user}', host='{db.host}', port='{db.port}',
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
    if with_postgis and 'postgis' not in extensions:
        extensions = ['postgis'] + list(extensions)

    # Try to run the drop and create commands with the postgres user; if
    # that user doesn't exist, run those commands as the current user.
    # This supports VM and Homebrew setups.
    result = local(config, 'id -u postgres', echo=False, hide='all', abort_on_failure=False)
    run_as = 'postgres' if result.succeeded else None

    def run_command(*command, superuser='postgres', database='postgres'):
        command = ' '.join(command)
        command = '"{command}"'.format(command=command)
        local(config, (
            'psql',
            '-U', superuser,
            '-h', host,
            '-p', port,
            '-d', database,
            '-c', command,
        ), run_as=run_as, abort_on_failure=False)

    run_command('CREATE USER', user, 'WITH SUPERUSER')

    if drop:
        run_command('DROP DATABASE', name) if drop else None

    run_command('CREATE DATABASE', name, 'WITH OWNER', user)

    for extension in extensions:
        run_command('CREATE EXTENSION', extension, database=name)


def create_mysql_db(config, user='{db.user}', host='{db.host}', port='{db.port}', name='{db.name}',
                    drop=False):
    """Create a MySQL database with the specified ``name``.

    This also creates the user specified by ``user`` as a superuser
    with no password. This is insecure and should only be used in
    development and testing.

    """
    def run_command(*command):
        command = ' '.join(command)
        command = '"{command}"'.format(command=command)
        local(config, (
            'mysql',
            '-h', host,
            '-p', port,
            '-u', 'root',
            '-e', command,
        ), abort_on_failure=False)

    f = locals()

    run_command("CREATE USER '{user}'@'{host}'".format_map(f))
    run_command("GRANT ALL PRIVILEGES on *.* TO '{user}'@'{host}' WITH GRANT OPTION".format_map(f))

    if drop:
        run_command('DROP DATABASE', name)

    run_command('CREATE DATABASE', name)
