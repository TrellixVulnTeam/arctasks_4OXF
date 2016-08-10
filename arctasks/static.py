import glob
import itertools
import os
from subprocess import PIPE, Popen

from .arctask import arctask
from .django import call_command, get_settings
from .remote import rsync
from .runners import local
from .util import abort, abs_path, args_to_str, as_list, get_path


@arctask(configured='dev')
def bower(ctx, where='{package}:static', update=False):
    which = local(ctx, 'which bower', echo=False, hide='stdout', abort_on_failure=False)
    if which.failed:
        abort(1, 'bower must be installed (via npm) and on $PATH')
    where = abs_path(where, format_kwargs=ctx)
    local(ctx, ('bower', 'update' if update else 'install'), cd=where)


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


@arctask(configured='dev')
def lessc(ctx, sources=None, optimize=True, autoprefixer_browsers=_autoprefixer_browsers):
    """Compile the LESS files specified by ``sources``.

    Each LESS file will be compiled into a CSS file with the same root
    name. E.g., "path/to/base.less" will be compiled to "path/to/base.css".

    TODO: Make destination paths configurable?

    """
    which = local(ctx, 'which lessc', echo=False, hide='stdout', abort_on_failure=False)
    if which.failed:
        abort(1, 'less must be installed (via npm) and on $PATH')
    sources = [abs_path(s, format_kwargs=ctx) for s in as_list(sources)]
    sources = [glob.glob(s) for s in sources]
    for source in itertools.chain(*sources):
        root, ext = os.path.splitext(source)
        if ext != '.less':
            abort(1, 'Expected a .less file; got "{source}"'.format(source=source))
        destination = '{root}.css'.format(root=root)
        local(ctx, (
            'lessc',
            '--autoprefix="%s"' % autoprefixer_browsers,
            '--clean-css' if optimize else '',
            source, destination
        ))


@arctask(configured='dev', timed=True)
def sass(ctx, sources=None, optimize=True, autoprefixer_browsers=_autoprefixer_browsers):
    """Compile the SASS files specified by ``sources``.

    Each SASS file will be compiled into a CSS file with the same root
    name. E.g., "path/to/base.scss" will be compiled to "path/to/base.css".

    TODO: Make destination paths configurable?

    """
    which = local(ctx, 'which node-sass', echo=False, hide='stdout', abort_on_failure=False)
    if which.failed:
        abort(1, 'node-sass must be installed (via npm) and on $PATH')
    sources = [abs_path(s, format_kwargs=ctx) for s in as_list(sources)]
    sources = [glob.glob(s) for s in sources]
    for source in itertools.chain(*sources):
        root, ext = os.path.splitext(source)

        if ext != '.scss':
            abort(1, 'Expected a .scss file; got "{source}"'.format(source=source))

        destination = '{root}.css'.format(root=root)

        sass_args = ['node-sass', source]
        postcss_args = [
            'postcss',
            '--use', 'autoprefixer',
            'autoprefixer.browsers', "'%s'" % autoprefixer_browsers
        ]
        cleancss_args = ['cleancss']

        path = 'PATH={path}'.format(path=get_path(ctx))
        env = os.environ.copy()
        env['PATH'] = ':'.join((path, env['PATH']))
        popen_kwargs = {'stdout': PIPE, 'stderr': PIPE, 'env': env}

        cmd = Popen(sass_args, **popen_kwargs)
        if autoprefixer_browsers:
            cmd = Popen(postcss_args, stdin=cmd.stdout, **popen_kwargs)
        if optimize:
            cmd = Popen(cleancss_args, stdin=cmd.stdout, **popen_kwargs)

        out, err = cmd.communicate()

        if cmd.returncode:
            abort(cmd.returncode, err.decode('utf-8').strip(), color=False)

        with open(destination, 'w') as fp:
            fp.write(out.decode('utf-8'))


@arctask(configured='dev')
def build_static(ctx, css=True, css_sources=None, js=True, js_sources=None, collect=True,
                 optimize=True, static_root=None):
    if css:
        if css_sources is None:
            static_config = ctx.get('arctasks', {}).get('static', {})
            css_sources = []
            css_sources.extend(static_config.get('lessc', {}).get('sources', ()))
            css_sources.extend(static_config.get('sass', {}).get('sources', ()))
        else:
            css_sources = as_list(css_sources)
        less_sources = [s for s in css_sources if s.endswith('less')]
        sass_sources = [s for s in css_sources if s.endswith('scss')]
        if less_sources:
            lessc(ctx, sources=less_sources, optimize=optimize)
        if sass_sources:
            sass(ctx, sources=sass_sources, optimize=optimize)
    if js:
        build_js(ctx, sources=js_sources, optimize=optimize)
    if collect:
        collectstatic(ctx, static_root=static_root)



@arctask(configured='dev')
def collectstatic(ctx, static_root=None):
    settings = get_settings()
    original_static_root = settings.STATIC_ROOT
    settings.STATIC_ROOT = static_root
    print('Collecting static files into {0.STATIC_ROOT}...'.format(settings))
    call_command('collectstatic', interactive=False, clear=True, hide=True)
    settings.STATIC_ROOT = original_static_root


@arctask(configured='dev')
def build_js(ctx, sources=None, main_config_file='{package}:static/requireConfig.js',
             base_url='{package}:static', optimize=True, paths=None):
    sources = [abs_path(s, format_kwargs=ctx) for s in as_list(sources)]
    sources = [glob.glob(s) for s in sources]
    main_config_file = abs_path(main_config_file, format_kwargs=ctx)
    base_url = abs_path(base_url, format_kwargs=ctx)
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
        local(ctx, cmd, hide='stdout')


@arctask(configured='prod')
def pull_media(ctx, user='{remote.user}', host='{remote.host}', run_as='{remote.run_as}'):
    """Pull media from specified env [prod] to ./media."""
    local(ctx, 'mkdir -p media')
    rsync(
        ctx, local_path='media', remote_path='{remote.path.media}/', source='remote',
        default_excludes=None)
