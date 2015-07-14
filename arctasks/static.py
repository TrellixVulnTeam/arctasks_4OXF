import os

from .arctask import arctask
from .django import call_command
from .runners import local
from .util import abort, abs_path, args_to_str, as_list


@arctask(configured='dev')
def bower(ctx, where=None, update=False):
    which = local(ctx, 'which bower', echo=False, hide='stdout', abort_on_failure=False)
    if which.failed:
        abort(1, 'bower must be installed (via npm) and on $PATH')
    where = abs_path(where, format_kwargs=ctx)
    local(ctx, ('bower', 'update' if update else 'install'), cd=where)


@arctask(configured='dev')
def lessc(ctx, sources=None, optimize=True, autoprefix_browsers=None):
    """Compile the LESS files specified by ``sources``.

    Each LESS file will be compiled into a CSS file with the same root
    name. E.g., "path/to/base.less" will compiled to "path/to/base.css".

    TODO: Make destination paths configurable?

    """
    which = local(ctx, 'which lessc', echo=False, hide='stdout', abort_on_failure=False)
    if which.failed:
        abort(1, 'less must be installed (via npm) and on $PATH')
    sources = [abs_path(s, format_kwargs=ctx) for s in as_list(sources)]
    for source in sources:
        root, ext = os.path.splitext(source)
        if ext != '.less':
            abort(1, 'Expected a .less file; got "{source}"'.format(source=source))
        destination = '{root}.css'.format(root=root)
        local(ctx, (
            'lessc',
            '--autoprefix="%s"' % autoprefix_browsers,
            '--clean-css' if optimize else '',
            source, destination
        ))


@arctask(configured='dev')
def build_static(ctx, js=True, js_sources=None, css=True, css_sources=None, collect=True,
                 optimize=True):
    if js:
        build_js(ctx, sources=js_sources, optimize=optimize)
    if css:
        lessc(ctx, sources=css_sources, optimize=optimize)
    if collect:
        call_command('collectstatic', '--noinput', '--clear', hide=True)


@arctask(configured='dev')
def build_js(ctx, sources=None, main_config_file=None, base_url=None, optimize=True, paths=None):
    sources = [abs_path(s, format_kwargs=ctx) for s in as_list(sources)]
    main_config_file = abs_path(main_config_file, format_kwargs=ctx)
    base_url = abs_path(base_url, format_kwargs=ctx)
    optimize = 'uglify' if optimize else 'none'
    paths = as_list(paths)
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
    local(ctx, cmd, hide='stdout')
