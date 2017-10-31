========
Backends
========

In ARC Tasks, the *backend* refers to the abstract implementation of the infrastructure
and resources your project intends to use.

Development
-----------

This backend provides a basic, naive implementation intended for use during development;
for example, orchestration tooling in a locally-provisioned environment or in combination with Docker.

OIT (Legacy)
------------

This backend provides the legacy behavior of ARC Tasks prior to v1.1. It supports the PSU OIT on-
premises infrastructure and provides only support for the deployment of applications. No support
is provided for resource definitions or management and all such activities must be performed out-of-band.

AWS
---

This backend provides all the basic tooling available in other backends in addition to resource and
infrastructure orchestration via the `cloud-config`_ package as well as application life-cycle support.

For further information on declaring resources, see the :doc:`resources` section.


.. _cloud-config: https://github.com/PSU-OIT-ARC/cloud-config
