import os

from taskrunner import task
from taskrunner.tasks import local
from taskrunner.util import abort, abs_path, as_list, print_info


def setup(config):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', config.get('django_settings_module'))
    os.environ.setdefault('LOCAL_SETTINGS_FILE', config.get('local_settings_file'))
    import django
    django.setup()


def get_settings(config):
    setup(config)
    import django.conf
    return django.conf.settings


def call_command(config, *args, hide=False, **kwargs):
    setup(config)
    import django.core.management
    try:
        if hide:
            with open(os.devnull, 'w') as devnull:
                django.core.management.call_command(*args, stdout=devnull, **kwargs)
        else:
            django.core.management.call_command(*args, **kwargs)
    except KeyboardInterrupt:
        abort(message='\nAborted Django management command')


@task(default_env='dev')
def manage(config, args, cd=None, sudo=False, run_as=None, echo=None, hide=None,
           abort_on_failure=True):
    local(
        config, ('{bin.python}', 'manage.py', args),
        cd=cd, sudo=sudo, run_as=run_as, echo=echo, hide=hide, abort_on_failure=abort_on_failure)


@task(default_env='dev')
def makemigrations(config, app=None):
    args = [app]
    args = [a for a in args if a]
    call_command(config, 'makemigrations', *args)


@task(default_env='dev')
def migrate(config, app=None, migration=None):
    if migration and not app:
        abort(1, 'You must specify an app to run a specific migration')
    args = [app, migration]
    args = [a for a in args if a]
    call_command(config, 'migrate', *args)


@task(default_env='test')
def test(config, test=None, failfast=False, keepdb=True, verbosity=1):
    args = [test]
    args = [a for a in args if a]
    call_command(config, 'test', *args, failfast=failfast, keepdb=keepdb, verbosity=verbosity)


@task(default_env='test')
def coverage(config, keepdb=True):
    from coverage import coverage
    cov = coverage(source=[config.package])
    cov.start()
    call_command(config, 'test', keepdb=keepdb)
    cov.stop()
    cov.report()


_runserver_host = '0.0.0.0'
_runserver_port = 8000


@task(default_env='dev')
def runserver(config, host=_runserver_host, port=_runserver_port):
    call_command(config, 'runserver', '{host}:{port}'.format(**locals()))


@task(default_env='dev')
def run_mod_wsgi(config, host=_runserver_host, port=_runserver_port, processes=2, threads=25,
                 aliases=None, proxies=None):
    aliases = as_list(aliases)
    proxies = as_list(proxies)

    settings = get_settings(config)
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

    local(config, (
        '{venv}/bin/mod_wsgi-express start-server {wsgi_file}',
        '--processes', str(processes),
        '--threads', str(threads),
        '--host', host,
        '--port', str(port),
        [('--url-alias', path, fs_path) for (path, fs_path) in aliases],
        [('--proxy-mount-point', path, url) for (path, url) in proxies],
        '--reload-on-changes --shutdown-timeout 1 --log-to-terminal',
    ))


@task(default_env='dev')
def shell(config):
    call_command(config, 'shell')


@task(default_env='dev')
def dbshell(config):
    call_command(config, 'dbshell')
