=========
ARC Tasks
=========

This package provides boilerplate and implements common tooling for Python projects
via the `runcommands package`_.

.. _runcommands package: https://github.com/PSU-OIT-ARC/runcommands

Getting Started
---------------

- Add ``psu.oit.arc.tasks`` to the project's requirements and, if applicable,
  to the ``install_requires`` section in the project ``setup.py``.

- Add a skeleton ``commands.py`` module to the project's top level directory::

    from arctasks.commands import *

- To use AWS-compatible commands, use the ``arctasks.aws`` package::

    from arctasks.aws.commands import *

- The default set of commands is now available and can be listed with ``runcommands``::

    me@there:~/code/myproject {venv}/bin/runcommands --list

- Add required project-specific configuration for ``runcommands``::

    [DEFAULT]
    extends = "{arctasks,arctasks.aws}:commands.cfg"

    name = "My Python Application"
    distribution = "psu.oit.wdt.mypythonproject"
    package = "mypythonproject"

Writing Custom Commands
-----------------------

Below is a simple example of an ``init`` command using only built-in commands::

    @command(default_env='dev', timed=True)
    def init(config, overwrite=False):
        virtualenv(config, overwrite=overwrite)
        install(config)  # Does `pip install -r requirements.txt` by default
        createdb(config, drop=overwrite)  # Creates a Postgres DB by default
        migrate(config)
        test(config, keepdb=False)
