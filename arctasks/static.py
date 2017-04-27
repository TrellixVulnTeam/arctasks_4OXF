import os
import shutil
from subprocess import Popen
from tempfile import NamedTemporaryFile

from runcommands import command
from runcommands.commands import local
from runcommands.runners.commands import get_default_local_prepend_path
from runcommands.util import abort, abs_path, args_to_str, Hide, printer

from .django import call_command, get_settings
from .remote import rsync
from .util import flatten_globs


@command(default_env='dev')
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


@command(default_env='dev')
def build_static(config, css=True, css_sources=(), js=True, js_sources=(), collect=True,
                 optimize=True, static_root=None, default_ignore=True, ignore=(), exclude=(),
                 include=(), echo=False, hide=None):
    if css:
        build_css(config, sources=css_sources, optimize=optimize, echo=echo, hide=hide)
    if js:
        build_js(config, sources=js_sources, optimize=optimize, echo=echo, hide=hide)
    if collect:
        collectstatic(
            config, static_root=static_root, default_ignore=default_ignore, ignore=ignore,
            exclude=exclude, include=include, echo=echo, hide=hide)


@command(default_env='dev')
def build_css(config, sources=(), optimize=True, echo=False, hide=None):
    if not sources:
        sources = []
        sources.extend(config._get_dotted('defaults.arctasks.static.lessc.sources', default=[]))
        sources.extend(config._get_dotted('defaults.arctasks.static.sass.sources', default=[]))
    less_sources = [s for s in sources if s.endswith('less')]
    sass_sources = [s for s in sources if s.endswith('scss')]
    if less_sources:
        lessc(config, sources=less_sources, optimize=optimize, echo=echo, hide=hide)
    if sass_sources:
        sass(config, sources=sass_sources, optimize=optimize, echo=echo, hide=hide)


@command(default_env='dev')
def lessc(config, sources=(), optimize=True, autoprefixer_browsers=_autoprefixer_browsers,
          echo=False, hide=None):
    """Compile the LESS files specified by ``sources``.

    Each LESS file will be compiled into a CSS file with the same root
    name. E.g., "path/to/base.less" will be compiled to "path/to/base.css".

    TODO: Make destination paths configurable?

    """
    which = local(config, 'which lessc', echo=False, hide='stdout', abort_on_failure=False)
    if which.failed:
        abort(1, 'less must be installed (via npm) and on $PATH')

    sources = flatten_globs(config, sources)

    for source in sources:
        root, ext = os.path.splitext(source)
        if ext != '.less':
            abort(1, 'Expected a .less file; got "{source}"'.format(source=source))
        destination = '{root}.css'.format(root=root)
        local(config, (
            'lessc',
            '--autoprefix="%s"' % autoprefixer_browsers,
            '--clean-css' if optimize else '',
            source, destination
        ), echo=echo, hide=hide)


@command(default_env='dev')
def sass(config, sources=(), optimize=True, autoprefixer_browsers=_autoprefixer_browsers,
         echo=False, hide=None):
    """Compile the SASS files specified by ``sources``.

    Each SASS file will be compiled into a CSS file with the same root
    name. E.g., "path/to/base.scss" will be compiled to "path/to/base.css".

    TODO: Make destination paths configurable?

    """
    sources = flatten_globs(config, sources)

    hide_stdout = Hide.hide_stdout(hide)
    echo = echo and not hide_stdout

    run_postcss = bool(optimize or autoprefixer_browsers)

    env = os.environ.copy()

    path = get_default_local_prepend_path(config)
    if path:
        env['PATH'] = os.pathsep.join((path, env['PATH']))

    for source in sources:
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


@command(default_env='dev')
def build_js(config, sources=(), main_config_file='{package}:static/requireConfig.js',
             base_url='{package}:static', optimize=True, paths=(), echo=False, hide=None):
    sources = flatten_globs(config, sources)

    main_config_file = abs_path(main_config_file, format_kwargs=config)
    base_url = abs_path(base_url, format_kwargs=config)
    optimize = 'uglify' if optimize else 'none'
    if paths:
        paths = ' '.join('paths.{k}={v}'.format(k=k, v=v) for k, v in paths.items())

    for source in sources:
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
        local(config, cmd, echo=echo, hide=hide)


_collectstatic_default_ignore = (
    'node_modules',
)


@command(default_env='dev')
def collectstatic(config, static_root=None, default_ignore=True, ignore=(), exclude=(), include=(),
                  echo=False, hide=None):
    settings = get_settings(config)
    override_static_root = bool(static_root)

    if override_static_root:
        static_root = static_root.format(**config)
        original_static_root = settings.STATIC_ROOT
        settings.STATIC_ROOT = static_root

    ignore = list(ignore)
    if default_ignore:
        ignore.extend(_collectstatic_default_ignore)

    hide_stdout = Hide.hide_stdout(hide)
    echo = echo and not hide_stdout

    if not os.path.isdir(settings.STATIC_ROOT):
        printer.info('{0.STATIC_ROOT} does not exist;'.format(settings), end=' ')
        os.makedirs(settings.STATIC_ROOT)
        printer.info('created')

    if echo:
        print('Collecting static files into {0.STATIC_ROOT} ...'.format(settings))

    args = {
        'interactive': False,
        'ignore': ignore,
        'clear': True,
        'hide': hide,
    }

    if include or exclude:
        args.update(exclude=exclude, include=include)

    call_command(config, 'collectstatic', **args)

    if override_static_root:
        settings.STATIC_ROOT = original_static_root


@command(default_env='prod')
def pull_media(config, user='{remote.user}', host='{remote.host}', run_as='{remote.run_as}'):
    """Pull media from specified env [prod] to ./media."""
    local(config, 'mkdir -p media')
    rsync(
        config, local_path='media', remote_path='{remote.path.media}/', user=user, host=host,
        run_as=run_as, source='remote', default_excludes=False)
