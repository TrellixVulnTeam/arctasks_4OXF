import os

from .arctask import arctask
from .runners import local
from .util import abort


DJANGO_SET_UP = False


def call_command(*args, hide=False, **kwargs):
    import django
    import django.core.management
    global DJANGO_SET_UP
    if not DJANGO_SET_UP:
        django.setup()
    DJANGO_SET_UP = True
    if hide:
        with open(os.devnull, 'w') as devnull:
            django.core.management.call_command(*args, stdout=devnull, **kwargs)
    else:
        django.core.management.call_command(*args, **kwargs)


@arctask(configured='dev')
def manage(ctx, command, **kwargs):
    call_command(command, **kwargs)


@arctask(configured='dev')
def makemigrations(ctx, app=None):
    args = [app]
    args = [a for a in args if a]
    call_command('makemigrations', *args)


@arctask(configured='dev')
def migrate(ctx, app=None, migration=None):
    if migration and not app:
        abort(1, 'You must specify an app to run a specific migration')
    args = [app, migration]
    args = [a for a in args if a]
    call_command('migrate', *args)


@arctask(configured='test')
def test(ctx, test=None, keepdb=True):
    args = [test]
    args = [a for a in args if a]
    call_command('test', *args, keepdb=keepdb)


@arctask(configured='test')
def coverage(ctx, keepdb=True):
    local(ctx, (
        'coverage run --source={package}',
        'manage.py test',
        '--keepdb' if keepdb else ''
    ))
    local(ctx, 'coverage report')
