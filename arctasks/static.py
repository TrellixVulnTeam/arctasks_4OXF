import glob
import itertools
import os
import shutil
from subprocess import Popen
from tempfile import NamedTemporaryFile

from taskrunner import task
from taskrunner.tasks import local
from taskrunner.runners.tasks import get_default_prepend_path
from taskrunner.util import abort, abs_path, args_to_str, as_list, Hide

from .django import call_command, get_settings
from .remote import rsync


@task(default_env='dev')
def bower(config, where='{package}:static', update=False):
    which = local(config, 'which bower', echo=False, hide='stdout', abort_on_failure=False)
    if which.failed:
        abort(1, 'bower must be installed (via npm) and on $PATH')
    where = abs_path(where, format_kwargs=config)
    local(config, ('bower', 'update' if update else 'install'), cd=where)


# Copied from Bootstrap (from grunt/configBridge.json in the source)
_autoprefixer_browsers = ','.join((
    'Android 2.3',
    'Android >= 4',
    'Chrome >= 20',
    'Firefox >= 24',
    'Explorer >= 8',
    'iOS >= 6',
    'Opera >= 12',
    'Safari >= 6',
))


@task(default_env='dev')
def lessc(config, sources=None, optimize=True, autoprefixer_browsers=_autoprefixer_browsers):
    """Compile the LESS files specified by ``sources``.

    Each LESS file will be compiled into a CSS file with the same root
    name. E.g., "path/to/base.less" will be compiled to "path/to/base.css".

    TODO: Make destination paths configurable?

    """
    which = local(config, 'which lessc', echo=False, hide='stdout', abort_on_failure=False)
    if which.failed:
        abort(1, 'less must be installed (via npm) and on $PATH')
    sources = [abs_path(s, format_kwargs=config) for s in as_list(sources)]
    sources = [glob.glob(s) for s in sources]
    for source in itertools.chain(*sources):
        root, ext = os.path.splitext(source)
        if ext != '.less':
            abort(1, 'Expected a .less file; got "{source}"'.format(source=source))
        destination = '{root}.css'.format(root=root)
        local(config, (
            'lessc',
            '--autoprefix="%s"' % autoprefixer_browsers,
            '--clean-css' if optimize else '',
            source, destination
        ))


@task(default_env='dev')
def sass(config, sources=None, optimize=True, autoprefixer_browsers=_autoprefixer_browsers,
         echo=False, hide=None):
    """Compile the SASS files specified by ``sources``.

    Each SASS file will be compiled into a CSS file with the same root
    name. E.g., "path/to/base.scss" will be compiled to "path/to/base.css".

    TODO: Make destination paths configurable?

    """
    sources = as_list(sources)
    sources = [abs_path(s, format_kwargs=config) for s in sources]

    for s in sources:
        if not glob.glob(s):
            abort(1, 'No SASS sources found for "{s}"'.format(s=s))

    sources = [glob.glob(s) for s in sources]

    hide_stdout = Hide.hide_stdout(hide)
    echo = echo and not hide_stdout

    run_postcss = bool(optimize or autoprefixer_browsers)

    path = 'PATH={path}'.format(path=get_default_prepend_path(config))
    env = os.environ.copy()
    env['PATH'] = ':'.join((path, env['PATH']))

    for source in itertools.chain(*sources):
        root, ext = os.path.splitext(source)
        destination = '{root}.css'.format(root=root)

        if not hide_stdout:
            print('Compiling {source} to {destination}'.format_map(locals()))

        if ext != '.scss':
            abort(1, 'Expected a .scss file; got "{source}"'.format(source=source))

        def do_or_die(args, in_file=None):
            if in_file is not None:
                in_file.seek(0)
            out_file = NamedTemporaryFile()
            if echo:
                print(' '.join(args))
            cmd = Popen(args, stdin=in_file, stdout=out_file, env=env)
            cmd.wait()
            if cmd.returncode:
                abort(cmd.returncode, 'Aborted due to errors', color=False)
            return out_file

        out = do_or_die(['node-sass', source])

        if run_postcss:
            postcss_args = ['postcss']

            if autoprefixer_browsers:
                postcss_args += [
                    '--use', 'autoprefixer',
                    '--autoprefixer.browsers', autoprefixer_browsers
                ]

            if optimize:
                postcss_args += ['--use', 'postcss-clean']

            out = do_or_die(postcss_args, in_file=out)

        shutil.copyfile(out.name, destination)


@task(default_env='dev')
def build_static(config, css=True, css_sources=None, js=True, js_sources=None, collect=True,
                 optimize=True, static_root=None, default_ignore=True, ignore=None):
    if css:
        build_css(config, sources=css_sources, optimize=optimize)
    if js:
        build_js(config, sources=js_sources, optimize=optimize)
    if collect:
        collectstatic(config, static_root=static_root, default_ignore=default_ignore, ignore=ignore)


@task(default_env='dev')
def build_css(config, sources=None, optimize=True):
    if sources is None:
        sources = []
        sources.extend(config._get_dotted('defaults.arctasks.static.lessc.sources', default=[]))
        sources.extend(config._get_dotted('defaults.arctasks.static.sass.sources', default=[]))
    else:
        sources = as_list(sources)
    less_sources = [s for s in sources if s.endswith('less')]
    sass_sources = [s for s in sources if s.endswith('scss')]
    if less_sources:
        lessc(config, sources=less_sources, optimize=optimize)
    if sass_sources:
        sass(config, sources=sass_sources, optimize=optimize)


_collectstatic_default_ignore = (
    'node_modules',
)


@task(default_env='dev')
def collectstatic(config, static_root=None, default_ignore=True, ignore=None):
    settings = get_settings(config)
    override_static_root = bool(static_root)

    if override_static_root:
        static_root = static_root.format(**config)
        original_static_root = settings.STATIC_ROOT
        settings.STATIC_ROOT = static_root

    ignore = as_list(ignore)
    if default_ignore:
        ignore.extend(_collectstatic_default_ignore)

    print('Collecting static files into {0.STATIC_ROOT} ...'.format(settings))
    call_command(config, 'collectstatic', interactive=False, ignore=ignore, clear=True, hide='all')

    if override_static_root:
        settings.STATIC_ROOT = original_static_root


@task(default_env='dev')
def build_js(config, sources=None, main_config_file='{package}:static/requireConfig.js',
             base_url='{package}:static', optimize=True, paths=None):
    sources = [abs_path(s, format_kwargs=config) for s in as_list(sources)]
    sources = [glob.glob(s) for s in sources]
    main_config_file = abs_path(main_config_file, format_kwargs=config)
    base_url = abs_path(base_url, format_kwargs=config)
    optimize = 'uglify' if optimize else 'none'
    paths = as_list(paths)
    if paths:
        paths = ' '.join('paths.{k}={v}'.format(k=k, v=v) for k, v in paths.items())
    for source in itertools.chain(*sources):
        name = os.path.relpath(source, base_url)
        if name.endswith('.js'):
            name = name[:-3]
        base_name = os.path.basename(name)
        out = os.path.join(os.path.dirname(source), '{}-built.js'.format(base_name))
        cmd = args_to_str((
            'r.js -o',
            'mainConfigFile={main_config_file}',
            'baseUrl={base_url}',
            'name={name}',
            'optimize={optimize}',
            paths or '',
            'out={out}',
        ), format_kwargs=locals())
        local(config, cmd, hide='stdout')


@task(default_env='prod')
def pull_media(config, user='{remote.user}', host='{remote.host}', run_as='{remote.run_as}'):
    """Pull media from specified env [prod] to ./media."""
    local(config, 'mkdir -p media')
    rsync(
        config, local_path='media', remote_path='{remote.path.media}/', user=user, host=host,
        run_as=run_as, source='remote', default_excludes=False)
