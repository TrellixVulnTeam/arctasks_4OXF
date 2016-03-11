"""Release-related tasks.

The main tasks are:

    - release; this runs the tasks below in order and will typically be
      the only task from this module that you need to run
    - prepare_release
    - merge_release
    - tag_release
    - resume_development

"""
import datetime
import os
import re
import subprocess

from .arctask import arctask
from .util import abort, confirm
from .util import print_error, print_header, print_info, print_success, print_warning


DEFAULT_CHANGELOG = 'CHANGELOG.md'
CHANGELOG_HEADER_RE = (
    r'(?P<hashes>#+ *)?'
    r'(?P<version>{version})'
    r' +- +'
    r'(?P<release_date>\d{{4}}-\d{{2}}-\d{{2}}|unreleased)'
)
SETUP_GLOBAL_VERSION_RE = r'VERSION += +(?P<quote>(\'|"))(?P<old_version>.+)(\'|")'
SETUP_VERSION_RE = r'version=(?P<quote>(\'|"))(?P<old_version>.+)(\'|"),'


@arctask(configured='dev')
def release(ctx, version, release_date=None, changelog=DEFAULT_CHANGELOG, merge_to_branch='master',
            tag_name=None, next_version=None, prepare=True, merge=True, tag=True, resume=True,
            dry_run=False, debug=False):
    """Cut a release.

    A typical run looks like this::

        inv release A.B.C --next-version X.Y.Z

    The steps involved are:

        - Preparation (see :func:`prepare_release`)
        - Merging (see :func:`merge_release`)
        - Tagging (see :func:`tag_release`)
        - Resuming development  (see :func:`resume_development`)

    All steps are run by default. To disable a step, pass the
    corresponding ``--no-{step}`` option. E.g.::

        inv release X.Y.Z --no-resume

    Args:
        version: The release version
        release_date: The release date; defaults to today
        changelog: The change log to update; defaults to ./CHANGELOG.md
        merge_to_branch: Branch to merge changes to; by default, we
            assume that development is done on the ``develop`` branch
            and will be merged into the ``master`` branch
        tag_name: Name of release tag; defaults to ``version`` (which
            should generally be preferred)
        next_version: Version to use when resuming development
        prepare: Prepare release?
        merge: Merge release?
        tag: Tag release?
        resume: Resume development?
        dry_run: Show what would be done, but don't actually do it
        debug: Show extra info that might be helpful for debugging

    TODO: Try to compute next version from version if next version
          isn't specified?

    """
    tag_name = tag_name or version
    args = dict(dry_run=dry_run, debug=debug)
    if prepare:
        prepare_release(ctx, version, release_date=release_date, changelog=changelog, **args)
    if merge:
        merge_release(ctx, version, to_branch=merge_to_branch, **args)
    if tag:
        tag_release(ctx, tag_name, **args)
    if resume:
        resume_development(ctx, next_version, changelog=changelog, **args)
    print_warning('NOTE: Released-related changes are *not* pushed automatically')
    print_warning('NOTE: You still need to `git push` and `git push --tags`')


@arctask(configured='dev')
def prepare_release(ctx, version, release_date=None, changelog=DEFAULT_CHANGELOG, dry_run=False,
                    debug=False):
    """Prepare a release.

    Preparation involves:

        - Updating the change log: setting the release date for the
          specified version (a section corresponding to ``version`` must
          exist in the change log)
        - Updating the distribution version: setting the ``version``
          keyword arg in ``setup()``
        - Freezing dependencies

    Args:
        version: The release version
        release_date: The release date; defaults to today
        changelog: The change log to update; defaults to ./CHANGELOG.md
        dry_run: Show what would be done, but don't actually do it
        debug: Show extra info that might be helpful for debugging

    """
    if dry_run:
        print_header('[DRY RUN]', end=' ')
    print_header('Preparing release: updating version and release date')

    if release_date is None:
        release_date = datetime.date.today().strftime('%Y-%m-%d')

    distribution = ctx.distribution

    f = locals()

    # Args passed to all find_and_update_line() calls
    find_and_update_line_args = {
        'dry_run': dry_run,
        'debug': debug,
    }

    # Find section for version in change log and update release date.

    def changelog_updater(match, line):
        hashes = match.group('hashes')
        if hashes:
            hashes = '{hashes} '.format(hashes=hashes.strip())
        else:
            hashes = ''
        return '{hashes}{version} - {release_date}'.format(hashes=hashes, **f)

    header_re = CHANGELOG_HEADER_RE.format(version=re.escape(version))

    not_found_message = '{changelog} appears to be missing a section for version {version}'
    not_found_message = not_found_message.format_map(f)
    find_and_update_line(
        changelog, header_re, changelog_updater,
        flags=re.I, not_found_message=not_found_message,
        **find_and_update_line_args
    )

    find_and_update_version(version, **find_and_update_line_args)

    # Freeze requirements
    with open('requirements-frozen.txt', 'w') as requirements_fp:
        subprocess.check_call(
            [ctx.bin.pip, 'freeze', '-f', ctx.remote.pip.find_links],
            stdout=requirements_fp)

    # Adjust frozen requirements:
    #   - Ensure distribution spec is correct in frozen requirements
    #   - Specify ARCTasks w/o a version
    with open('requirements-frozen.txt') as requirements_fp:
        requirements = requirements_fp.readlines()
    skip_requirements = (distribution, 'psu.oit.arc.tasks')
    skip_requirement = lambda r: any((d in r) for d in skip_requirements)
    adjusted_requirements = [r for r in requirements if not skip_requirement(r)]
    adjusted_requirements[1:1] = [
        '{distribution}=={version}\n'.format_map(f),
        'psu.oit.arc.tasks\n',
    ]

    with open('requirements-frozen.txt', 'w') as requirements_fp:
        requirements_fp.writelines(adjusted_requirements)

    if not dry_run:
        commit_message = 'Prepare release {version}'.format_map(f)
        commit_files(ctx, [changelog, 'setup.py', 'requirements-frozen.txt'], commit_message)


@arctask(configured='dev')
def merge_release(ctx, version, to_branch='master', dry_run=False, debug=False):
    """Merge release.

    By default, this does a "no fast forward" merge into master.

    Args:
        version: Used in merge commit message
        to_branch: Branch to merge changes to; by default, we
            assume that development is done on the ``develop`` branch
            and will be merged into the ``master`` branch
        dry_run: Show what would be done, but don't actually do it
        debug: Show extra info that might be helpful for debugging

    TODO: Implement dry run functionality.

    """
    current_branch = subprocess.check_output(['git', 'symbolic-ref', '--short', 'HEAD'])
    current_branch = current_branch.decode('utf-8').strip()
    f = locals()
    subprocess.check_call(['git', 'log', '--oneline', '--reverse', '{to_branch}..'.format_map(f)])
    if not confirm(ctx, 'Merge these changes into {to_branch}?'.format_map(f), yes_values=('yes',)):
        abort(message='Aborted merge from {current_branch} to {to_branch}'.format_map(f))
    commit_message = "Merge branch '{current_branch}' for release {version}".format_map(f)
    subprocess.check_call(['git', 'checkout', to_branch])
    subprocess.check_call(['git', 'merge', '--no-ff', current_branch, '-m', commit_message])
    subprocess.check_call(['git', 'checkout', current_branch])


@arctask(configured='dev')
def tag_release(ctx, tag_name, to_branch='master', dry_run=False, debug=False):
    """Tag release.

    By default, this tags the master branch as ``version``. It's assumed
    that the latest commit on the master branch is a merge commit such as
    :func:`merge_release` creates.

    Args:
        tag_name: Tag name for release; also used in annotated tag's
            message (note: this should typically be the same as the
            release version)
        to_branch: Branch to merge changes to; by default, we
            assume that development is done on the ``develop`` branch
            and will be merged into the ``master`` branch
        dry_run: Show what would be done, but don't actually do it
        debug: Show extra info that might be helpful for debugging

    TODO: Implement dry run functionality.

    """
    f = locals()
    commit = subprocess.check_output(['git', 'log', '--oneline', '-1', to_branch])
    commit = commit.decode('utf-8').strip()
    print_info('Commit that will be tagged on {to_branch}:\n    '.format_map(f), commit)
    if not confirm(ctx, 'Tag this commit as {tag_name}?'.format_map(f)):
        abort(message='Aborted tagging of release')
    commit_message = 'Release {tag_name}'.format_map(f)
    subprocess.check_call(['git', 'tag', '-a', '-m', commit_message, tag_name, to_branch])


@arctask(configured='dev')
def resume_development(ctx, version, changelog=DEFAULT_CHANGELOG, dry_run=False, debug=False):
    """Resume development.

    Args:
        version: Version to continue working at
        changelog: The change log to update; defaults to ./CHANGELOG.md
        dry_run: Show what would be done, but don't actually do it
        debug: Show extra info that might be helpful for debugging

    TODO: Implement dry run functionality.

    """
    distribution = ctx.distribution

    if version is None:
        version = input('Version for new release (.dev0 will be appended): ')

    f = locals()

    with open(changelog) as fp:
        lines = fp.readlines()

    with open(changelog, 'w') as fp:
        new_lines = [
            '\n',
            '## {version} - unreleased\n'.format_map(f),
            '\n',
            'In progress...\n',
            '\n',
        ]
        lines[1:1] = new_lines
        fp.writelines(lines)

    dev_version = '{version}.dev0'.format(version=version)
    find_and_update_version(dev_version, dry_run=dry_run, debug=debug)
    os.remove('requirements-frozen.txt')

    commit_message = 'Resume development at {version}'.format_map(f)
    commit_files(ctx, [changelog, 'setup.py'], commit_message)


# Utilities


def commit_files(ctx, files, commit_message):
    """Commit files with message.

    This will show a diff and ask for confirmation before committing. It
    will also prompt the user for a commit message, using the passed
    ``commit_message`` as the default.

    Args:
        files (list): The files to commit
        commit_message: The default commit message

    """
    f = locals()
    output = subprocess.check_output(['git', 'diff', '--color=always'] + files)
    output = output.strip()
    if not output:
        abort(1, 'Nothing to commit')
    print(output.decode('utf-8'))
    if not confirm(ctx, 'Commit this?'):
        abort(message='Aborted commit')
    default_commit_message = commit_message
    commit_message = input('Commit message ["{commit_message}"] '.format_map(f))
    commit_message = commit_message.strip() or default_commit_message
    subprocess.check_call(['git', 'commit', '-m', commit_message] + files)


def find_and_update_line(file_name, pattern, line_updater, flags=0, abort_when_not_found=True,
                         not_found_message=None, dry_run=False, debug=False):
    """Find line matching pattern and update it.

    Leading & trailing whitespace is ignored.

    Args:
        file_name (str): Name of file to search in.
        pattern (str): Regular expression pattern to search for. The
            first line matching this pattern will be updated. Note that
            this should *not* be anchored nor should it include leading
            and trailing whitespace.
        line_updater (function): Function that updates the matched line.
            This will be passed the match object and the original line.
        flags: Flags for :func:`re.search`. E.g.: ``re.I``.
        abort_when_not_found (bool): The default behavior is to abort
            when no line matching ``pattern`` is found.
        not_found_message (str): An optional additional message to show
            when no line matching ``pattern`` is found.
        dry_run: Show what would be done, but don't actually do it
        debug: Show extra info that might be helpful for debugging

    Returns:
        bool: Indicates whether a line was found and updated.

    """
    pattern = r''.join((
        r'^'
        r'(?P<leading_whitespace>\s*)',
        pattern,
        r'(?P<trailing_whitespace>\s*)',
        r'$'
    ))

    updated_line_template = '{leading_whitespace}{line}{trailing_whitespace}'

    f = locals()

    if debug:
        print_info('Searching for a line matching "{pattern}" in {file_name}...'.format_map(f))

    with open(file_name) as fp:
        lines = fp.readlines()

    for i, line in enumerate(lines):
        match = re.search(pattern, line, flags)
        if match:
            original_line = line
            updated_line = line_updater(match, line)
            updated_line = updated_line_template.format(line=updated_line, **match.groupdict())
            lines[i] = updated_line
            line_number = i + 1
            if debug:
                print_error('-', original_line, sep='', end='')
                print_success('+', line, sep='', end='')
            break
    else:
        # No line matching pattern was found
        if debug:
            print_error('No line matching "{pattern}" found in {file_name}'.format_map(f))
        if abort_when_not_found:
            abort(1, not_found_message)
        elif not_found_message:
            print_error(not_found_message)
        return False

    if dry_run:
        print_info('[DRY RUN] Updated {file_name} contents would be:'.format_map(f))
        for j, line in enumerate(lines):
            if i == j:
                print_error('-', original_line, sep='', end='')
                print_success('+', line, sep='', end='')
            else:
                print(' ', line, sep='', end='')
        print('\n')
    else:
        with open(file_name, 'w') as fp:
            fp.writelines(lines)
        f = locals()
        print_info('Updated line {line_number} of {file_name}'.format_map(f))

    return True


def find_and_update_version(version, **kwargs):
    """Find distribution version and update it.

    This is a special case of :func:`find_and_update_line`. It looks for
    the version in a few places (in order of precedence):

        - VERSION file
        - setup.py in VERSION global
        - setup.py in version keyword arg

    Args:
        version: The new version
        kwargs: Keyword args for :func:`find_and_update_line`

    """
    f = locals()
    if os.path.isfile('VERSION'):
        def version_updater(match, line):
            return version
        not_found_message = 'No version found in VERSION file'
        find_and_update_line(
            'VERSION', r'.+', version_updater,
            not_found_message=not_found_message,
            **kwargs
        )
    else:
        def global_version_updater(match, line):
            return match.expand(r'VERSION = \g<quote>{version}\g<quote>'.format_map(f))
        found = find_and_update_line(
            'setup.py', SETUP_GLOBAL_VERSION_RE, global_version_updater,
            abort_when_not_found=False,
            **kwargs
        )
        if not found:
            def version_updater(match, line):
                return match.expand(r'version=\g<quote>{version}\g<quote>,'.format_map(f))
            not_found_message = (
                'Could not find VERSION global in setup.py or version keyword arg in setup()')
            find_and_update_line(
                'setup.py', SETUP_VERSION_RE, version_updater,
                not_found_message=not_found_message,
                **kwargs
            )
