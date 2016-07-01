import re

from . import git
from .arctask import arctask


@arctask
def total_time_spent(ctx, key, debug=False):
    """Show total hours spent on a project.

    Parses JIRA smart commits for #time. Smart commits look like this::

        QT-10 #in-progress #time 30m

    Args:
        key: The JIRA project key; for example: "QT"
        debug: Show matching lines when this is set

    """
    seconds = []

    # Search in just the body of each commit
    result = git.run('log --pretty=format:%b', return_output=True)

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
    print('%s hours' % (seconds / 60 / 60))
