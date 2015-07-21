import os

from .arctask import arctask
from .runners import local
from .util import abort

try:
    import django
except ImportError:
    DJANGO_INSTALLED = False
else:
    import django.conf
    import django.core.management
    DJANGO_INSTALLED = True


DJANGO_SET_UP = False


def setup():
    get_settings()
    global DJANGO_SET_UP
    if not DJANGO_SET_UP:
        django.setup()
    DJANGO_SET_UP = True


def get_settings():
    if DJANGO_INSTALLED:
        return django.conf.settings
    else:
        abort(1, 'Django is not installed')


def call_command(*args, hide=False, **kwargs):
    setup()
    if hide:
        with open(os.devnull, 'w') as devnull:
            django.core.management.call_command(*args, stdout=devnull, **kwargs)
    else:
        django.core.management.call_command(*args, **kwargs)


@arctask(configured='dev')
def manage(ctx, args, cd=None, sudo=False, run_as=None, echo=True, hide=False,
           abort_on_failure=True):
    local(
        ctx, ('{python}', 'manage.py', args),
        cd=cd, sudo=sudo, run_as=run_as, echo=echo, hide=hide, abort_on_failure=abort_on_failure)


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
    from coverage import coverage
    cov = coverage(source=[ctx.package])
    cov.start()
    call_command('test', keepdb=keepdb)
    cov.stop()
    cov.report()


@arctask(configured='dev')
def runserver(ctx, host=None, port=None):
    call_command('runserver', '{host}:{port}'.format(**locals()))


@arctask(configured='dev')
def run_mod_wsgi(ctx, host=None, port=None, processes=2, threads=25):
    local(ctx, (
        '{bin}/mod_wsgi-express start-server {package}/wsgi.py',
        '--processes', str(processes),
        '--threads', str(threads),
        '--host', host,
        '--port', str(port),
        '--url-alias /media media',
        '--url-alias /static static',
        '--reload-on-changes --shutdown-timeout 1 --log-to-terminal',
    ))


@arctask(configured='dev')
def shell(ctx):
    call_command('shell')


@arctask(configured='dev')
def dbshell(ctx):
    call_command('dbshell')
