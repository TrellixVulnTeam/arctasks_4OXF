from invoke.tasks import ctask as task

from .config import configured
from .runners import local


@task(configured)
def createdb(ctx, type=None, name='{db.name}', drop=False):
    if type is None:
        type = ctx.db.type
    if type == 'mysql':
        create_mysql_db(ctx, name, drop)
    elif type == 'postgresql':
        create_postgresql_db(ctx, name, drop)
    else:
        raise ValueError('Unknown database type: {db.type}'.format(**ctx))


@task
def create_postgresql_db(ctx, name='{db.name}', drop=False):
    """Create a PostgreSQL database with the specified ``name``."""
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


@task
def create_mysql_db(ctx, name='{db.name}', drop=False):
    raise NotImplementedError
