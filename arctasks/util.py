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


# The functions below should be disused and then removed.


def as_list(items, sep=','):
    # Convert ``items`` to list.
    #
    # - None -> []
    # - '' -> []
    # - non-empty str -> items split on comma
    # - list -> items
    # - any other type -> items
    if items is None:
        items = []
    elif isinstance(items, str):
        if items == '':
            items = []
        else:
            items = items.strip().split(sep)
            items = [item.strip() for item in items]
    return items


def as_tuple(items, sep=','):
    # Same as ``as_list`` with ``items`` converted to tuple.
    return tuple(as_list(items, sep))
