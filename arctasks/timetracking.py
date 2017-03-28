import re

from runcommands import command

from . import git


@command
def time_spent(config, key, after=None, since=None, rate=0, debug=False):
    """Show time spent on a project based on git history.

    Parses JIRA smart commits for #time. Smart commits look like this::

        QT-10 #in-progress #time 30m

    By default, the total time spent on the project is reported. This
    can be constrained by specifying a commit (usually a tag) or a date;
    the time spent *after* the commit or date will be reported.

    Args:
        key: The JIRA project key; for example: "QT"
        after: A tag or other commit; if this is specified, only commits
            *after* it will be included
        since: A date in ``YYYY-MM-DD`` format (or any date format that
            ``git log`` accepts); if this specified, only commits *after*
            the specified date will be included
        rate: Hourly rate; if this something other than zero, the total
            cost of included hours will be shown
        debug: Show matching lines when this is set

    Examples::

        # Show time spent after release 1.2.0
        run time_spent NPULSE --after 1.2.0

        # Show time spent after a specific date
        run time_spent NPULSE --since 2016-07-11

    """
    seconds = []
    args = ['log']
    if after:
        args.append('{after}..'.format_map(locals()))
    if since:
        args.extend(('--since', since))

    # Search in just the body of each commit
    result = git.run(args, return_output=True)

    pattern = (
        r'{key}-\d+'
        r'\s+.*'
        r'#time\s+(?P<amount>\d+)(?P<unit>(m|h))'
    )
    pattern = pattern.format(key=key)
    regex = re.compile(pattern)

    for line in result.splitlines():
        line = line.strip()
        match = regex.search(line)
        if match:
            if debug:
                print(line)
            amount = match.group('amount')
            amount = int(amount)
            unit = match.group('unit')
            if unit == 'm':
                amount *= 60
            elif unit == 'h':
                amount *= 3600
            else:
                raise ValueError('Unknown unit: %s' % unit)
            seconds.append(amount)

    seconds = sum(seconds)
    hours = seconds / 60 / 60
    dollars = rate * hours if rate else None
    f = locals()

    print('{hours:.2f}h'.format_map(f), end='')
    if dollars is not None:
        print(' at ${rate}/h = ${dollars:.2f}'.format_map(f), end='')
    print()
