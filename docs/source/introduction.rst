=========
ARC Tasks
=========

Introduction
------------

This package provides configuration boilerplate and implements common tooling for managing the
release cycle of software projects via the `runcommands package`_.

.. _runcommands package: https://github.com/PSU-OIT-ARC/runcommands

Getting started
---------------

To get started using ARC Tasks, integrate it into a new or existing project with the following steps.

Add *psu.oit.arc.tasks* to the project's requirements. For any project::

  curl -L https://raw.githubusercontent.com/PSU-OIT-ARC/arctasks/release/1.1/bootstrap.sh | bash -

For existing Python projects, you may add the dependency directly to the *install_requires* section
of its *setup.py*::

  ...

  install_requires=[
      'psu.oit.arc.tasks>=1.1.0'
      ...
  ]

  ...

Select the backend that is appropriate for your project and add a skeleton *commands.py* module
to the project's top level directory::

    from arctasks.{backend}.commands import *

.. note:: Review the :doc:`backends` section for information on the available backends.

The default set of commands available for use can be listed with ``runcommands``::

    foo@baz:~/code/myproject {venv}/bin/runcommands --list

Finally, add the minimal project-specific configuration for ``runcommands``::

    [DEFAULT]
    extends = "arctasks.{backend}:commands.cfg"

    name = "My Application"
    distribution = "org.myorg.apps.myproject"
    package = "myproject"

.. note:: Consult the :doc:`configuration` section for information on the available configuration attributes and their use.
