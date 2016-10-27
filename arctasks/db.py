import os
from getpass import getpass
from tempfile import mkstemp

from invoke import Context

from .arctask import arctask
from .config import configure
from .runners import local
from .util import abort, as_tuple, confirm


@arctask(configured='dev')
def createdb(ctx, type=None, host='{db.host}', user='{db.user}', name='{db.name}', drop=False,
             with_postgis=False, extensions=()):
    if type is None:
        type = ctx.db.type
    if type == 'mysql':
        create_mysql_db(ctx, host, user, name, drop)
    elif type == 'postgresql':
        create_postgresql_db(ctx, host, user, name, drop, with_postgis, extensions)
    else:
        raise ValueError('Unknown database type: {db.type}'.format(**ctx))


def create_postgresql_db(ctx, host='{db.host}', user='{db.user}', name='{db.name}', drop=False,
                         with_postgis=False, extensions=()):
    """Create a PostgreSQL database with the specified ``name``.

    This also creates the user specified by ``user`` as a superuser
    with no password. This is insecure and should only be used in
    development and testing.

    The --with-postgis flag can be used to spatially-enable the
    database. This only works with PostgreSQL 9.1+ and PostGIS 2.0+.

    """
    extensions = as_tuple(extensions)
    if with_postgis and 'postgis' not in extensions:
        extensions = ('postgis',) + extensions

    # Try to run the drop and create commands with the postgres user; if
    # that user doesn't exist, run those commands as the current user.
    # This supports VM and Homebrew setups.
    result = local(ctx, 'id -u postgres', echo=False, hide=True, abort_on_failure=False)
    run_as = 'postgres' if result.ok else None

    def run_command(*command, database='postgres'):
        command = ' '.join(command)
        command = '"{command}"'.format(command=command)
        local(ctx, (
            'psql',
            '-h', host,
            '-d', database,
            '-c', command,
        ), run_as=run_as, abort_on_failure=False)

    run_command('CREATE USER', user, 'WITH SUPERUSER')

    if drop:
        run_command('DROP DATABASE', name) if drop else None

    run_command('CREATE DATABASE', name, 'WITH OWNER', user)

    for extension in extensions:
        run_command('CREATE EXTENSION', extension, database=name)


def create_mysql_db(ctx, host='{db.host}', user='{db.user}', name='{db.name}', drop=False):
    """Create a MySQL database with the specified ``name``.

    This also creates the user specified by ``user`` as a superuser
    with no password. This is insecure and should only be used in
    development and testing.

    """
    def run_command(*command):
        command = ' '.join(command)
        command = '"{command}"'.format(command=command)
        local(ctx, (
            'mysql',
            '-h', host,
            '-u', 'root',
            '-e', command,
        ), abort_on_failure=False)

    f = locals()

    run_command("CREATE USER '{user}'@'{host}'".format(**f))
    run_command("GRANT ALL PRIVILEGES on *.* TO '{user}'@'{host}' WITH GRANT OPTION".format(**f))

    if drop:
        run_command('DROP DATABASE', name)

    run_command('CREATE DATABASE', name)


@arctask(configured='dev')
def load_prod_data(ctx, schema='public', source='prod'):
    """Load data from prod database directly into env database.

    This is generally intended for fetching a fresh copy of production
    data into the dev database. As such, this will typically be run like
    so::

        inv createdb -d load_prod_data

    You can also choose another data source, such as 'stage'::

        inv createdb -d load_prod_data --source stage

    To refresh the stage database, you'd run this instead::

        inv stage reset_db load_prod_data

    """
    if ctx.env == 'prod':
        abort(1, 'Cannot load data into prod database')
    if ctx.env == source:
        abort(1, 'Cannot load data into source database')
    source_ctx = Context()
    configure(source_ctx, source)
    source_pw = getpass('{source} database password: '.format(**locals()))
    env_pw = getpass('{env} database password: '.format(**ctx))
    temp_fd, temp_path = mkstemp()
    if ctx.db.type == 'postgresql':
        if source_pw:
            os.environ['PGPASSWORD'] = source_pw
        local(ctx, (
            'pg_dump',
            '--format', 'custom',
            '-U', source_ctx.db.user,
            '-h', source_ctx.db.host,
            '-d', source_ctx.db.name,
            '--schema', schema,
            '--blobs',
            '--no-acl',
            '--no-owner',
            '--no-privileges',
            '--file', temp_path,
        ))
        if env_pw:
            os.environ['PGPASSWORD'] = env_pw
        local(ctx, (
            'pg_restore',
            '-U {db.user}',
            '-h {db.host}',
            '-d {db.name}',
            '--no-owner',
            temp_path,
        ))
        os.close(temp_fd)
        os.remove(temp_path)
    elif ctx.db.type == 'mysql':
        raise NotImplementedError('load_prod_data not yet implemented for MySQL')
    else:
        raise ValueError('Unknown database type: {db.type}'.format(**ctx))


@arctask(configured=True)
def reset_db(ctx, host='{db.host}', user='{db.user}', name='{db.name}', truncate=False):
    """DROP CASCADE tables in database.

    This drops all tables owned by the app user in the public schema
    except for PostGIS tables.

    This is mainly intended to clear out the stage database during the
    early stages of development when there may be a lot of schema churn
    or test data. You'd run this and then reapply migrations to get a
    nice clean database.

    Another option is to TRUNCATE tables instead of dropping them. You
    might use this option if you want to load some new data.

    This can also be run in dev, and other non-prod environments. It
    cannot be run in prod.

    """
    if ctx.env == 'prod':
        abort(1, 'reset_db cannot be run on the prod database')
    host = host.format_map(ctx)
    user = user.format_map(ctx)
    name = name.format_map(ctx)
    op = 'TRUNCATE' if truncate else 'DROP'
    msg = (
        'Do you really want to reset the {{env}} database ({user}@{host}/{name})?\n'
        'This will {op} CASCADE all tables (excluding PostGIS tables).'.format_map(locals()))
    if not confirm(ctx, msg):
        abort(0)
    password = getpass('{env} database password: '.format(**ctx))
    if password:
        os.environ['PGPASSWORD'] = password
    psql = ('psql', '-h', host, '-U', user, '-d', name)
    result = local(ctx, (
        psql, '--tuples-only --command "',
        "SELECT tablename "
        "FROM pg_tables "
        "WHERE schemaname = 'public' "
        "AND tableowner = '" + user + "' "
        "AND tablename NOT IN ('geography_columns', 'geometry_columns', 'spatial_ref_sys');",
        '"',
    ), hide='stdout')
    tables = sorted(s.strip() for s in result.stdout.strip().splitlines())
    if not tables:
        abort(1, 'No tables found to drop')
    statements = ['{op} TABLE "{table}" CASCADE;'.format(op=op, table=table) for table in tables]
    print('\nThe following statements will be run:\n')
    print('    {statements}\n'.format(statements='\n    '.join(statements)))
    msg = 'Are you sure you want to do this (you must type out "yes")?'
    if confirm(ctx, msg, yes_values=('yes',)):
        local(ctx, (psql, '-c "', statements, '"'))
    else:
        print('Cancelled')
