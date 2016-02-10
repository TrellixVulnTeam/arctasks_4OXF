import os
from getpass import getpass
from tempfile import mkstemp

from invoke import Context

from .arctask import arctask
from .config import configure
from .runners import local
from .util import abort, confirm


@arctask(configured='dev')
def createdb(ctx, type=None, name='{db.name}', drop=False, with_postgis=None):
    if type is None:
        type = ctx.db.type
    if type == 'mysql':
        create_mysql_db(ctx, name, drop)
    elif type == 'postgresql':
        create_postgresql_db(ctx, name, drop, with_postgis)
    else:
        raise ValueError('Unknown database type: {db.type}'.format(**ctx))


def create_postgresql_db(ctx, name='{db.name}', drop=False, with_postgis=False):
    """Create a PostgreSQL database with the specified ``name``.

    The --with-postgis flag can be used to spatially-enable the
    database. This only works with PostgreSQL 9.1+ and PostGIS 2.0+.

    """
    # Try to run the drop and create commands with the postgres user; if
    # that user doesn't exist, run those commands as the current user.
    # This supports VM and Homebrew setups.
    result = local(ctx, 'id -u postgres', echo=False, hide=True, abort_on_failure=False)
    args = {
        'abort_on_failure': False,
        'run_as': 'postgres' if result.ok else None,
    }
    if drop:
        local(ctx, ('dropdb', name), **args)
    local(ctx, ('createdb', name), **args)
    if with_postgis:
        local(ctx, ('psql -d', name, '-c "CREATE EXTENSION postgis;"'), **args)


def create_mysql_db(ctx, name='{db.name}', drop=False):
    """Create a MySQL database with the specified ``name``."""
    if drop:
        local(ctx, ('mysql -u root -e "DROP DATABASE', name, '"'), abort_on_failure=False)
    local(ctx, ('mysql -u root -e "CREATE DATABASE', name, '"'), abort_on_failure=False)


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
            '-U', source_ctx.db.user,
            '-h', source_ctx.db.host,
            '-d', source_ctx.db.name,
            '--schema', schema,
            '--no-acl',
            '--no-owner',
            '--no-privileges',
            '--file', temp_path,
        ))
        if env_pw:
            os.environ['PGPASSWORD'] = env_pw
        local(ctx, (
            'psql',
            '-U {db.user}',
            '-h {db.host}',
            '-d {db.name}',
            '--file', temp_path,
        ))
        os.close(temp_fd)
        os.remove(temp_path)
    elif ctx.db.type == 'mysql':
        raise NotImplementedError('load_prod_data not yet implemented for MySQL')
    else:
        raise ValueError('Unknown database type: {db.type}'.format(**ctx))


@arctask(configured=True)
def reset_db(ctx, truncate=False):
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
    op = 'TRUNCATE' if truncate else 'DROP'
    msg = (
        'Do you really want to reset the {env} database ({db.user}@{db.host}/{db.name})?\n'
        'This will %s CASCADE all tables (excluding PostGIS tables).' % op)
    if not confirm(ctx, msg):
        abort(0)
    password = getpass('{env} database password: '.format(**ctx))
    if password:
        os.environ['PGPASSWORD'] = password
    psql = 'psql -h {db.host} -U {db.user} {db.name}'
    result = local(ctx, (
        psql, '--tuples-only --command "',
        "SELECT tablename "
        "FROM pg_tables "
        "WHERE schemaname = 'public' "
        "AND tableowner = '{db.user}' "
        "AND tablename NOT IN ('geography_columns', 'geometry_columns', 'spatial_ref_sys');",
        '"',
    ), hide='stdout')
    tables = sorted(s.strip() for s in result.stdout.strip().splitlines())
    if not tables:
        abort(1, 'No tables found to drop')
    statements = ['{op} TABLE {table} CASCADE;'.format(op=op, table=table) for table in tables]
    print('\nThe following statements will be run:\n')
    print('    {statements}\n'.format(statements='\n    '.join(statements)))
    msg = 'Are you sure you want to do this (you must type out "yes")?'
    if confirm(ctx, msg, yes_values=('yes',)):
        local(ctx, (psql, '-c "', statements, '"'))
    else:
        print('Cancelled')
