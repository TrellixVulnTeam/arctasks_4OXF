from glob import glob

from runcommands.util import abort, abs_path


def flatten_globs(config, sources, check_exists=True):
    flattened_sources = []
    for source in sources:
        source = abs_path(source, format_kwargs=config)
        paths = glob(source)
        if not paths and check_exists:
            abort(1, 'No sources found for "{source}"'.format(source=source))
        flattened_sources.extend(paths)
    return flattened_sources
