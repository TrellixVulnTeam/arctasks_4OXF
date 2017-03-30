import os

from runcommands import command
from runcommands.commands import local
from runcommands.util import Hide, abort, abs_path, as_list, printer


def setup(config):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', config.get('django_settings_module'))
    os.environ.setdefault('LOCAL_SETTINGS_FILE', config.get('local_settings_file'))
    import django
    django.setup()


def get_settings(config):
    setup(config)
    import django.conf
    return django.conf.settings


def call_command(config, *args, hide=None, **kwargs):
    setup(config)
    import django.core.management
    try:
        if hide:
            with open(os.devnull, 'w') as devnull:
                stdout = devnull if Hide.hide_stdout(hide) else None
                stderr = devnull if Hide.hide_stderr(hide) else None
                django.core.management.call_command(*args, stdout=stdout, stderr=stderr, **kwargs)
        else:
            django.core.management.call_command(*args, **kwargs)
    except KeyboardInterrupt:
        abort(message='\nAborted Django management command')


@command(default_env='dev')
def manage(config, args, cd=None, sudo=False, run_as=None, echo=None, hide=None,
           abort_on_failure=True):
    local(
        config, ('{bin.python}', 'manage.py', args),
        cd=cd, sudo=sudo, run_as=run_as, echo=echo, hide=hide, abort_on_failure=abort_on_failure)


@command(default_env='dev')
def makemigrations(config, app=None):
    args = [app]
    args = [a for a in args if a]
    call_command(config, 'makemigrations', *args)


@command(default_env='dev')
def migrate(config, app=None, migration=None):
    if migration and not app:
        abort(1, 'You must specify an app to run a specific migration')
    args = [app, migration]
    args = [a for a in args if a]
    call_command(config, 'migrate', *args)


@command(default_env='test')
def test(config, test_=(), failfast=False, keepdb=True, verbosity=1, with_coverage=False,
         force_env=None):
    if force_env and force_env != config.env:
        # NOTE: We have to use a subprocess for this because calling
        # django.setup() again in the same process will have no effect.
        printer.warning(
            'Forcing tests to run in {force_env} env instead of {config.env}'
            .format_map(locals()))

        # Don't propagate these to the subprocess
        django_settings_module = os.environ.pop('DJANGO_SETTINGS_MODULE', None)
        local_settings_file = os.environ.pop('LOCAL_SETTINGS_FILE', None)

        local(config, (
            'runcommand', '--env', force_env, 'test',
            [('--test', t) for t in test_],
            '--failfast' if failfast else '',
            '--keepdb' if keepdb else '',
            '--verbosity', str(verbosity),
            '--with-coverage' if with_coverage else '',
        ), echo=config.debug)

        if django_settings_module is not None:
            os.environ['DJANGO_SETTINGS_MODULE'] = django_settings_module
        if local_settings_file is not None:
            os.environ['LOCAL_SETTINGS_FILE'] = local_settings_file
    else:
        if with_coverage:
            from coverage import coverage
            cov = coverage(source=[config.package])
            cov.start()
        call_command(config, 'test', *test_, failfast=failfast, keepdb=keepdb, verbosity=verbosity)
        if with_coverage:
            cov.stop()
            cov.report()


@command(default_env='test')
def coverage(config, keepdb=True):
    from coverage import coverage
    cov = coverage(source=[config.package])
    cov.start()
    call_command(config, 'test', keepdb=keepdb)
    cov.stop()
    cov.report()


_runserver_host = '0.0.0.0'
_runserver_port = 8000


@command(default_env='dev')
def runserver(config, host=_runserver_host, port=_runserver_port):
    call_command(config, 'runserver', '{host}:{port}'.format(**locals()))


@command(default_env='dev')
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
        printer.info('Alias', path, '=>', fs_path)

    for (path, url) in proxies:
        printer.info('Proxy', path, '=>', url)

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


@command(default_env='dev')
def shell(config):
    call_command(config, 'shell')


@command(default_env='dev')
def dbshell(config):
    call_command(config, 'dbshell')
