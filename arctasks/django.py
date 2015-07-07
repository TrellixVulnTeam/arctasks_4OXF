from .arctask import arctask
from .runners import local
from .util import abort


@arctask(configured='dev')
def manage(ctx, args, cd=None, sudo=False, run_as=None, echo=True, hide=False,
           abort_on_failure=True):
    """Run a Django management command."""
    local(ctx, ('{python}', 'manage.py', args), cd, sudo, run_as, echo, hide, abort_on_failure)


@arctask(configured='dev')
def makemigrations(ctx, app=''):
    manage(ctx, ('makemigrations', app))


@arctask(configured='dev')
def migrate(ctx, app='', migration=''):
    args = ('migrate', app, migration)
    if migration and not app:
        abort(1, 'You must specify an app to run a specific migration')
    manage(ctx, args)


@arctask(configured='test')
def test(ctx, test='', keepdb=True):
    manage(ctx, ('test', '--keepdb' if keepdb else '', test))


@arctask(configured='test')
def coverage(ctx, keepdb=True):
    local(ctx, (
        'coverage run --source={package}',
        'manage.py test',
        '--keepdb' if keepdb else ''
    ))
    local(ctx, 'coverage report')
