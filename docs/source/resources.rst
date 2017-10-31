=========
Resources
=========

For backends with resource support, ARC Tasks allows you to declaratively define and manage
infrastructure resources required by your project.

Currently, support for resource management is only available in the *AWS* backend.

Create a resource
-----------------

Resources are generated from template fragments which reference an authoritative CloudFormation
document in the `cloud-config`_ repository and are bundled together into an environment-specific
application bundle.

Create a new application bundle for the *stage* environment::

  foo@baz:~/code/myproject {venv}/bin/runcommands -e stage create-application-stack

You should now see newly-generated fragment *cloudformation/app-stage.template.yml*.

Add resources to this bundle by specifying the resource name::

  foo@baz:~/code/myproject {venv}/bin/runcommands -e stage add-resource-to-stack host
  foo@baz:~/code/myproject {venv}/bin/runcommands -e stage add-resource-to-stack networking

This application bundle is now capable of provisioning a web host with the appropriate networking
and security configuration.

Add additional resources as the project requires::

  foo@baz:~/code/myproject {venv}/bin/runcommands -e stage add-resource-to-stack rds

.. note:: Consult the `cloud-config` repository for information on the available attributes
          when defining resources.

Managing secrets
----------------



.. _cloud-config: https://github.com/PSU-OIT-ARC/cloud-config
