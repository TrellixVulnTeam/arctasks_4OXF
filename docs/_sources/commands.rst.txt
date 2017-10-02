========
Commands
========

ARC Tasks currently provides two implementations targetting distinct deployment environments.

Example
-------

Below is a simple example of an ``init`` command using only built-in commands::

    @command(default_env='dev', timed=True)
    def init(config, overwrite=False):
        virtualenv(config, overwrite=overwrite)
        install(config)  # Does `pip install -r requirements.txt` by default
        createdb(config, drop=overwrite)  # Creates a Postgres DB by default
        migrate(config)
        test(config, keepdb=False)

Legacy
------

The top-level package `arctasks` and its command configuration `arctasks:commands.cfg` implement
the basic workflow to manage releases and deployment for projects deployed on the OIT infrastructure.
To configure a project for these workflows, use `arctasks.commands.cfg` in the project configuration
and use::

    from arctasks.commands import *

to import commands in the projects `commands` module.

.. note:: Future work for this package will involve extracting functionality specific to this infrastructure into
          a new module `arctasks.oit` and its corresponding command configuration into `arctasks.oit:commands.cfg`.

AWS Support
-----------

The `arctasks.aws` package and its corresponding configuration `arctasks.aws:commands.cfg` extend
the basic implementation to modify workflows and to include additional commands which expose
functionality specific to AWS deployments.

An example configuration::

    [DEFAULT]
    extends = "arctasks.aws:commands.cfg"

    ...

The following is an example `commands` module which implements a deployment workflow. Note the
use of the `post_install` step to handle resource initialization::

    from arctasks.aws.commands import *

    @command
    def deploy_app(config, provision=False, createdb=False):
        if provision:
            provision_webhost(config, with_gis=True)
        if createdb:
            createdb_aws(config, with_gis=True)

        deploy_aws(config, post_install=(
            migrate_db,
            rebuild_index
        ))
