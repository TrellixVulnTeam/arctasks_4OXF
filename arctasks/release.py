"""Release-related commands.

The main commands are:

    - release; this runs the commands below in order and will typically be
      the only command from this module that you need to run
    - prepare_release
    - merge_release
    - tag_release
    - resume_development

"""
import datetime
import os
import re
import subprocess

from runcommands import command
from runcommands.util import abort, abs_path, confirm, printer

from . import git


__all__ = [
    'release',
    'prepare_release',
    'merge_release',
    'tag_release',
    'resume_development',
]


DEFAULT_CHANGELOG = 'CHANGELOG.md'
CHANGELOG_HEADER_RE = (
    r'(?P<hashes>#+ *)?'
    r'(?P<version>{version}|next)'
    r' +- +'
    r'(?P<release_date>\d{{4}}-\d{{2}}-\d{{2}}|unreleased)'
)
FALLBACK_CHANGELOG_HEADER_RE = (
    r'(?P<hashes>#+ *)?'
    r'(?P<version>[^ ]+)'
    r' +- +'
    r'(?P<release_date>unreleased)'
)
SETUP_GLOBAL_VERSION_RE = r'VERSION += +(?P<quote>(\'|"))(?P<old_version>.+)(\1)'
SETUP_VERSION_RE = r'version=(?P<quote>(\'|"))(?P<old_version>.+)(\1),'


@command(default_env='dev')
def release(config, version, release_date=None, changelog=DEFAULT_CHANGELOG,
            freeze_requirements=True, merge_to_branch='master', tag_name=None, next_version=None,
            prepare=True, merge=True, tag=True, resume=True, dry_run=False, debug=False):
    """Cut a release.

    A typical run looks like this::

        run release A.B.C --next-version X.Y.Z

    The steps involved are:

        - Preparation (see :func:`prepare_release`)
        - Merging (see :func:`merge_release`)
        - Tagging (see :func:`tag_release`)
        - Resuming development  (see :func:`resume_development`)

    All steps are run by default. To disable a step, pass the
    corresponding ``--no-{step}`` option. E.g.::

        run release X.Y.Z --no-resume

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
        prepare_release(
            config, version, release_date=release_date, changelog=changelog,
            freeze_requirements=freeze_requirements, **args)
    if merge:
        merge_release(config, version, to_branch=merge_to_branch, **args)
    if tag:
        tag_release(config, tag_name, **args)
    if resume:
        resume_development(config, next_version, changelog=changelog, **args)
    printer.warning('NOTE: Release-related changes are *not* pushed automatically')
    printer.warning('NOTE: You still need to `git push` and `git push --tags`')


@command(default_env='dev')
def prepare_release(config, version, release_date=None, changelog=DEFAULT_CHANGELOG,
                    freeze_requirements=True, dry_run=False, debug=False):
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
    distribution = config.distribution

    if release_date is None:
        release_date = datetime.date.today().strftime('%Y-%m-%d')

    f = locals()

    print_dry_run_header(dry_run)
    printer.header('Preparing release {version} - {release_date}'.format_map(f))

    # Args passed to all find_and_update_line() calls
    find_and_update_line_args = {
        'dry_run': dry_run,
        'debug': debug,
    }

    find_and_update_changelog_header(changelog, version, release_date, **find_and_update_line_args)
    version_file = find_and_update_version(version, **find_and_update_line_args)
    files_to_commit = [changelog, version_file]

    if freeze_requirements:
        # Freeze requirements
        requirements_file = os.devnull if dry_run else 'requirements-frozen.txt'
        with open(requirements_file, 'w') as requirements_fp:
            subprocess.check_call(
                [config.bin.pip, 'freeze', '-f', config.remote.pip.find_links],
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
        with open(requirements_file, 'w') as requirements_fp:
            if dry_run:
                printer.info('[DRY RUN] New requirements-frozen.txt content would be:')
                print(''.join(adjusted_requirements))
            else:
                requirements_fp.writelines(adjusted_requirements)
        files_to_commit.append('requirements-frozen.txt')

    commit_message = 'Prepare release {version}'.format_map(f)
    if dry_run:
        printer.info('[DRY RUN] Prepare commit message:')
        print(commit_message)
    else:
        git.commit_files(files_to_commit, commit_message)


@command(default_env='dev')
def merge_release(config, version, to_branch='master', dry_run=False, debug=False):
    """Merge release.

    By default, this does a "no fast forward" merge into master.

    Args:
        version: Used in merge commit message
        to_branch: Branch to merge changes to; by default, we
            assume that development is done on the ``develop`` branch
            and will be merged into the ``master`` branch
        dry_run: Show what would be done, but don't actually do it
        debug: Show extra info that might be helpful for debugging

    """
    current_branch = git.current_branch()
    f = locals()
    if current_branch == to_branch:
        msg = (
            'Cannot merge {current_branch} branch into itself\n'
            'Check to make sure you are releasing from the branch you intended'
        )
        abort(1, msg.format_map(f))
    print_dry_run_header(dry_run)
    printer.header('Merging {current_branch} into {to_branch} for release {version}'.format_map(f))
    git.run(['log', '--oneline', '--reverse', '{to_branch}..'.format_map(f)])
    commit_message = "Merge branch '{current_branch}' for release {version}".format_map(f)
    if dry_run:
        printer.info('[DRY RUN] Merge commit message:')
        print(commit_message)
        return
    confirm_msg = 'Merge these changes into {to_branch}?'.format_map(f)
    if not confirm(config, confirm_msg, yes_values=('yes',)):
        abort(message='Aborted merge from {current_branch} to {to_branch}'.format_map(f))
    git.run(['checkout', to_branch])
    git.run(['merge', '--no-ff', current_branch, '-m', commit_message])
    git.run(['checkout', current_branch])


@command(default_env='dev')
def tag_release(config, tag_name, to_branch='master', dry_run=False, debug=False):
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

    """
    f = locals()
    print_dry_run_header(dry_run)
    printer.header('Tagging release {tag_name} on {to_branch}'.format_map(f))
    commit = git.run(['log', '--oneline', '-1', to_branch], return_output=True)
    printer.info('Commit that will be tagged on {to_branch}:\n    '.format_map(f), commit)
    commit_message = 'Release {tag_name}'.format_map(f)
    if dry_run:
        printer.info('[DRY RUN] Tag commit message:')
        print(commit_message)
        return
    if not confirm(config, 'Tag this commit as {tag_name}?'.format_map(f)):
        abort(message='Aborted tagging of release')
    git.tag(tag_name, to_branch, message=commit_message)


@command(default_env='dev')
def resume_development(config, version=None, changelog=DEFAULT_CHANGELOG, dry_run=False,
                       debug=False):
    """Resume development.

    Resuming development consists of:

        - Adding a section for the next ``version`` to the change log
        - Updating the distribution version
        - Unfreezing frozen requirements (because frozen requirements
          aren't helpful in development, especially when staging in-
          development versions)

    Args:
        version: Version to continue working at
        changelog: The change log to update; defaults to ./CHANGELOG.md
        dry_run: Show what would be done, but don't actually do it
        debug: Show extra info that might be helpful for debugging

    """
    distribution = config.distribution

    if version is None:
        version = input('Version for new release (.dev0 will be appended): ')

    f = locals()

    print_dry_run_header(dry_run)
    printer.header('Resuming development at {version}'.format_map(f))

    # Add section for next version to change log
    with open(changelog) as fp:
        lines = fp.readlines()
    with open((os.devnull if dry_run else changelog), 'w') as fp:
        new_lines = [
            '\n',
            '## {version} - unreleased\n'.format_map(f),
            '\n',
            'In progress...\n',
            '\n',
        ]
        lines[1:1] = new_lines
        if dry_run:
            printer.info('[DRY RUN] Added change log section for {version}'.format_map(f))
        else:
            fp.writelines(lines)

    # Update package version
    dev_version = '{version}.dev0'.format(version=version)
    version_file = find_and_update_version(dev_version, dry_run=dry_run, debug=debug)

    files_to_commit = [changelog, version_file]

    # Unfreeze requirements
    if os.path.isfile('requirements-frozen.txt'):
        files_to_commit.append('requirements-frozen.txt')
        with open(abs_path('arctasks:templates/requirements.txt.template')) as fp:
            contents = fp.read().format_map(config)
        with open((os.devnull if dry_run else 'requirements-frozen.txt'), 'w') as fp:
            if dry_run:
                printer.info('[DRY RUN] New requirements-frozen.txt content would be:')
                print(contents)
            else:
                fp.write(contents)

    commit_message = 'Resume development at {version}'.format_map(f)
    if dry_run:
        printer.info('[DRY RUN] Resume commit message:')
        print(commit_message)
    else:
        git.commit_files(files_to_commit, commit_message)


def print_dry_run_header(dry_run):
    if dry_run:
        printer.header('[DRY_RUN]', end=' ')


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
        printer.info('Searching for a line matching "{pattern}" in {file_name}...'.format_map(f))

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
                printer.error('-', original_line, sep='', end='')
                printer.success('+', updated_line, sep='', end='')
            break
    else:
        # No line matching pattern was found
        if debug:
            printer.error('No line matching "{pattern}" found in {file_name}'.format_map(f))
        if abort_when_not_found:
            abort(1, not_found_message)
        elif not_found_message:
            printer.error(not_found_message)
        return False

    if dry_run:
        printer.info('[DRY RUN] Updated {file_name} contents would be:'.format_map(f))
        for j, line in enumerate(lines):
            if i == j:
                printer.error('-', original_line, sep='', end='')
                printer.success('+', line, sep='', end='')
            else:
                print(' ', line, sep='', end='')
        print('\n')
    else:
        with open(file_name, 'w') as fp:
            fp.writelines(lines)
        f = locals()
        printer.info('Updated line {line_number} of {file_name}'.format_map(f))

    return True


def find_and_update_changelog_header(changelog, version, release_date, **kwargs):
    """Find section for version in change log and update release date.

    This looks for the following patterns (leading hashes are
    optional)::

        ## <version> - <release_date>
        ## <version> - unreleased
        ## next - <release_date>
        ## next - unreleased
        ## <any version> - unreleased

    The last pattern is used as a fallback where the current unreleased
    section in the change log has a different version than the version
    that's being released. A typical scenario is that the change log
    looks like this::

        ## 2.8.0 - unreleased

        In progress...

        ## 2.7.0 - 2016-03-30

        Changes that comprise 2.7.0.

    but you want to do a 2.7.1 patch release.

    """
    f = locals()

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
    found_changelog_header = find_and_update_line(
        changelog, header_re, changelog_updater,
        flags=re.I, not_found_message=not_found_message, abort_when_not_found=False,
        **kwargs
    )

    if not found_changelog_header:
        find_and_update_line(
            changelog, FALLBACK_CHANGELOG_HEADER_RE, changelog_updater,
            flags=re.I, not_found_message=not_found_message,
            **kwargs
        )


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
    Returns:
        The file where the version was found

    """
    if os.path.isfile('VERSION'):
        version_file = 'VERSION'

        find_and_update_line(
            'VERSION',
            r'.+',
            lambda match, line: version,
            not_found_message='No version found in VERSION file',
            **kwargs
        )
    else:
        version_file = 'setup.py'

        found = find_and_update_line(
            version_file,
            SETUP_GLOBAL_VERSION_RE,
            lambda match, line: match.expand(r'VERSION = \g<quote>%s\g<quote>' % version),
            abort_when_not_found=False,
            **kwargs
        )

        if not found:
            find_and_update_line(
                version_file,
                SETUP_VERSION_RE,
                lambda match, line: match.expand(r'version=\g<quote>%s\g<quote>,' % version),
                not_found_message=(
                    'Could not find VERSION global in setup.py or version keyword arg in setup()'),
                **kwargs
            )

    return version_file
