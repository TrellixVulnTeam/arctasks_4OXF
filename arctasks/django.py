from invoke.tasks import ctask as task

from .config import configure, configured
from .runners import local
from .util import abort


@task(configured)
def manage(ctx, args, cd=None, sudo=False, run_as=None, echo=True, hide=False,
           abort_on_failure=True):
    """Run a Django management command."""
    local(ctx, ('{python}', 'manage.py', args), cd, sudo, run_as, echo, hide, abort_on_failure)


@task(configured)
def makemigrations(ctx, app=''):
    manage(ctx, ('makemigrations', app))


@task(configured)
def migrate(ctx, app='', migration=''):
    args = ('migrate', app, migration)
    if migration and not app:
        abort(1, 'You must specify an app to run a specific migration')
    manage(ctx, args)


@task
def test(ctx, test=''):
    configure(ctx, 'test')
    manage(ctx, ('test', test))
