=========
ARC Tasks
=========

This package provides boilerplate and implements common tooling for Python projects
via the `runcommands package`_.

.. _runcommands package: https://github.com/PSU-OIT-ARC/runcommands

Getting Started
---------------

Add ``psu.oit.arc.tasks`` to the project's requirements and, if applicable,
to the ``install_requires`` section in the project's ``setup.py``.

Add a skeleton ``commands.py`` module to the project's top level directory::

    from arctasks.commands import *

To use AWS-compatible commands, use the ``arctasks.aws`` package::

    from arctasks.aws.commands import *

The default set of commands is now available and can be listed with ``runcommands``::

    me@there:~/code/myproject {venv}/bin/runcommands --list

Add required project-specific configuration for ``runcommands``::

    [DEFAULT]
    extends = "{arctasks,arctasks.aws}:commands.cfg"

    name = "My Python Application"
    distribution = "psu.oit.wdt.mypythonproject"
    package = "mypythonproject"

Documentation
-------------

For further information and usage notes consult the project's `full documentation`_.

.. _full documentation: https://psu-oit-arc.github.io/arctasks
