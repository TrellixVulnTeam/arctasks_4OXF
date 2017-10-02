import os
import posixpath

from runcommands import command
from runcommands.commands import remote
from runcommands.util import printer

from arctasks.remote import copy_file
from arctasks.deploy import Deployer, deploy as _deploy


__all__ = [
    'deploy_aws',

    'push_uwsgi_config',
    'restart_uwsgi',
]


class AWSDeployer(Deployer):
    """
    TBD
    """
    def push(self):
        # Create build root (ensure that it exists).
        remote(self.config, 'mkdir -p {remote.build.root}',
               cd='{remote.path.root}',
               run_as='{service.user}')

        super(AWSDeployer, self).push()

    def make_active(self):
        # Copying the uWSGI config file will cause the app's uWSGI process
        # to restart automatically.
        push_uwsgi_config(self.config)
        # restart_uwsgi(self.config)

        super(AWSDeployer, self).make_active()


@command(default_env='stage', timed=True)
def deploy_aws(config, version=None, provision=True, overwrite=False, push=True,
               static=True, build_static=True, deps=(), remove_distributions=(),
               wheels=True, install=True, post_install=(), push_config=True,
               make_active=True, set_permissions=False):
    _deploy(config, version=version, deployer_class=AWSDeployer, provision=provision,
            overwrite=overwrite, push=push, static=static, build_static=build_static,
            deps=deps, remove_distributions=remove_distributions, wheels=wheels,
            install=install, post_install=post_install, push_config=push_config,
            make_active=make_active, set_permissions=set_permissions)


@command(env=True)
def push_uwsgi_config(config):
    template = '{remote.uwsgi.config_file}'
    destination = '/etc/uwsgi/{package}.ini'
    copy_file(config, template, destination, template=True, sudo=True)


@command(env=True)
def restart_uwsgi(config):
    """Restart the app's uWSGI process."""
    remote(config, 'touch /etc/uwsgi/{package}.ini', sudo=True)
