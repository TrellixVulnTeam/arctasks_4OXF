=============
Configuration
=============

ARC Tasks is configured via the use of extensible `commands.cfg` definitions. At a minimum,
projects using this package are required to define the following::

    [DEFAULT]
    extends = "{arctasks,arctasks.aws}:commands.cfg"

    name = "My Python Application"
    distribution = "psu.oit.wdt.mypythonproject"
    package = "mypythonproject"

Common Settings
---------------

+--------------------------+---------------------------------------------------------+
| Attribute                | Description                                             |
+--------------------------+---------------------------------------------------------+
| `python.version`         | The major version used for local environments.          |
+--------------------------+---------------------------------------------------------+
| `remote.python.version`  | The major version used for remote environments.         |
+--------------------------+---------------------------------------------------------+
| `remote.host`            | The hostname of the remote environment.                 |
+--------------------------+---------------------------------------------------------+
| `remote.user`            | The identity to use when creating remote sessions.      |
|                          | Default: the local environments current user.           |
+--------------------------+---------------------------------------------------------+
| `service.user`           | The identity of the remotely-deployed application.      |
|                          | Default: the local environments current user.           |
+--------------------------+---------------------------------------------------------+
| `domain_name`            | The DNS name of the remotely-deployed application.      |
+--------------------------+---------------------------------------------------------+
