import os

from .arctask import arctask
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


@arctask
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
        local(ctx, ('psql -d', name, '-c "CREATE EXTENSION postgis;"'))


@arctask
def create_mysql_db(ctx, name='{db.name}', drop=False):
    raise NotImplementedError


@arctask(configured=True)
def reset_db(ctx, truncate=False, password=None):
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

    Passing ``--password`` will set the ``PGPASSWORD`` environment
    variable so you don't have to enter it multiple times. Standard
    caveats about passing passwords via shell commands apply (i.e.,
    don't use ``--password`` where someone might be able to access your
    shell history).

    """
    if ctx.env == 'prod':
        abort(1, 'reset_db cannot be run on the prod database')
    op = 'TRUNCATE' if truncate else 'DROP'
    msg = (
        'Do you really want to reset the {env} database ({db.user}@{db.host}/{db.name})?\n'
        'This will %s CASCADE all tables (excluding PostGIS tables).' % op)
    if not confirm(ctx, msg):
        abort(0)
    if password is not None:
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
