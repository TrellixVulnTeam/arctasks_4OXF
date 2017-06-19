from packaging.version import parse
from pkg_resources import find_distributions, get_distribution
from subprocess import check_call, CalledProcessError, DEVNULL

from runcommands import command
from runcommands.util import abort, printer


@command
def show_upgraded_packages(config):
    """Show packages that have been upgraded.

    Compares the specified minimum version of each requirement to the
    version that's actually installed.

    Shows the name, specified minimum version, and installed version for
    each requirement that is newer than its minimum version.

    Basically, this provides an easy way to show which declared
    requirements can be updated after running ``pip install --upgrade``
    (or, in some cases, requirements that should be constrained).

    For example, if the specified version of the requirement "xyz" is
    ">1.2" and the installed version of "xyz" is "1.3", this will
    output::

        xyz 1.2 => 1.3

    Requirements without a specified version are skipped.

    This will also show a warning for any installed requirement with
    version outside its specified range.

    """
    setup_cmd = ['python', 'setup.py', 'egg_info']
    try:
        check_call(setup_cmd, stdout=DEVNULL)
    except CalledProcessError:
        abort(1, 'Could not run `%s`' % ' '.join(setup_cmd))

    dist = next(find_distributions('.', True), None)
    if dist is None:
        abort(1, 'Could not find a Python distribution in current directory')

    requirements = dist.requires()

    for req in requirements:
        if not req.specs:
            continue

        specs = [(op, parse(v)) for (op, v) in req.specs]
        specified_min_op, specified_min_version = min(specs, key=lambda item: item[1])
        specified_max_op, specified_max_version = max(specs, key=lambda item: item[1])

        dep = get_distribution(req.name)
        installed_version = parse(dep.version)

        if specified_min_version < installed_version:
            print(dep.project_name, specified_min_version, '=>', installed_version)

        if not req.specifier.contains(str(installed_version)):
            printer.warning(
                '{dep.project_name} {installed_version} '
                'is not in range specified in requirements: '
                '{specified_min_op}{specified_min_version},'
                '{specified_max_op}{specified_max_version}'
                .format_map(locals()))
