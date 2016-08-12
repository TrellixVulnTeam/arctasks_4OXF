import os

from .arctask import arctask
from .runners import local
from .util import abort, abs_path, as_list, print_info


DJANGO_SET_UP = False


def setup():
    get_settings()
    global DJANGO_SET_UP
    if not DJANGO_SET_UP:
        import django
        django.setup()
    DJANGO_SET_UP = True


def get_settings():
    try:
        import django
    except ImportError:
        abort(1, 'Django is not installed')
    import django.conf
    return django.conf.settings


def call_command(*args, hide=False, **kwargs):
    setup()
    import django.core.management
    try:
        if hide:
            with open(os.devnull, 'w') as devnull:
                django.core.management.call_command(*args, stdout=devnull, **kwargs)
        else:
            django.core.management.call_command(*args, **kwargs)
    except KeyboardInterrupt:
        abort(message='\nAborted Django management command')


@arctask(configured='dev')
def manage(ctx, args, cd=None, sudo=False, run_as=None, echo=None, hide=None,
           abort_on_failure=True):
    local(
        ctx, ('{bin.python}', 'manage.py', args),
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
def test(ctx, test=None, failfast=False, keepdb=True, verbosity=1):
    args = [test]
    args = [a for a in args if a]
    call_command('test', *args, failfast=failfast, keepdb=keepdb, verbosity=verbosity)


@arctask(configured='test')
def coverage(ctx, keepdb=True):
    from coverage import coverage
    cov = coverage(source=[ctx.package])
    cov.start()
    call_command('test', keepdb=keepdb)
    cov.stop()
    cov.report()


_runserver_host = '0.0.0.0'
_runserver_port = 8000


@arctask(configured='dev')
def runserver(ctx, host=_runserver_host, port=_runserver_port):
    call_command('runserver', '{host}:{port}'.format(**locals()))


@arctask(configured='dev')
def run_mod_wsgi(ctx, host=_runserver_host, port=_runserver_port, processes=2, threads=25,
                 aliases=None, proxies=None):
    aliases = as_list(aliases)
    proxies = as_list(proxies)

    settings = get_settings()
    media_url = settings.MEDIA_URL.rstrip('/')
    static_url = settings.STATIC_URL.rstrip('/')
    default_media_alias = (media_url, settings.MEDIA_ROOT)
    default_static_alias = (static_url, settings.STATIC_ROOT)

    has_alias = lambda url: any((path == url) for (path, _) in aliases)

    if not has_alias(media_url):
        aliases.append(default_media_alias)
    if not has_alias(static_url):
        aliases.append(default_static_alias)

    aliases = [(path, abs_path(fs_path)) for (path, fs_path) in aliases]

    for (path, fs_path) in aliases:
        print_info('Alias', path, '=>', fs_path)

    for (path, url) in proxies:
        print_info('Proxy', path, '=>', url)

    local(ctx, (
        '{bin.dir}/mod_wsgi-express start-server {wsgi_file}',
        '--processes', str(processes),
        '--threads', str(threads),
        '--host', host,
        '--port', str(port),
        [('--url-alias', path, fs_path) for (path, fs_path) in aliases],
        [('--proxy-mount-point', path, url) for (path, url) in proxies],
        '--reload-on-changes --shutdown-timeout 1 --log-to-terminal',
    ))


@arctask(configured='dev')
def shell(ctx):
    call_command('shell')


@arctask(configured='dev')
def dbshell(ctx):
    call_command('dbshell')
