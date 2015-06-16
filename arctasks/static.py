import os
import pkg_resources

from invoke.tasks import ctask as task

from .config import configured
from .django import manage
from .runners import local
from .util import abort, args_to_str, as_list


@task(configured)
def bower(ctx, update=False):
    which = local(ctx, 'which bower', echo=False, hide='stdout', abort_on_failure=False)
    if which.failed:
        abort(1, 'bower must be installed (via npm) and on $PATH')
    local(ctx, ('bower', 'update' if update else 'install'), cd='{package}/static')


@task(configured)
def lessc(ctx, sources=None, optimize=True):
    """Compile the LESS files specified by ``sources``.

    Each LESS file will be compiled into a CSS file with the same root
    name. E.g., "path/to/base.less" will compiled to "path/to/base.css".

    TODO: Make destination paths configurable?

    """
    which = local(ctx, 'which lessc', echo=False, hide='stdout', abort_on_failure=False)
    if which.failed:
        abort(1, 'less must be installed (via npm) and on $PATH')
    if sources is None:
        sources = ctx.task.lessc.sources
    sources = as_list(sources)
    for source in sources:
        root, ext = os.path.splitext(source)
        if ext != '.less':
            abort(1, 'Expected a .less file; got "{source}"'.format(source=source))
        destination = '{root}.css'.format(root=root)
        local(ctx, (
            'lessc',
            '--autoprefix="{task.lessc.autoprefix.browsers}"',
            '--clean-css' if optimize else '',
            source, destination
        ))


@task(configured)
def build_static(ctx, js=True, js_sources=None, css=True, css_sources=None, collect=True,
                 optimize=True):
    if js:
        build_js(ctx, js_sources, optimize)
    if css:
        lessc(ctx, css_sources, optimize)
    if collect:
        manage(ctx, 'collectstatic --noinput --clear', hide='stdout')


@task(configured)
def build_js(ctx, sources=None, optimize=True):
    sources = sources or ctx.task.build_js.sources
    sources = as_list(sources)
    optimize = 'uglify' if optimize else 'none'
    main_config_file = pkg_resources.resource_filename(ctx.package, 'static/requireConfig.js')
    base_url = pkg_resources.resource_filename(ctx.package, 'static')
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
            'out={out}',
        ), format_kwargs=locals())
    local(ctx, cmd, hide='stdout')
