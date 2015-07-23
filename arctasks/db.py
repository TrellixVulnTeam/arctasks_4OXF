from .arctask import arctask
from .runners import local


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
