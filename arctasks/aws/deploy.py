import os
import posixpath

from runcommands import command
from runcommands.commands import remote

from arctasks.remote import copy_file
from arctasks.deploy import Deployer


__all__ = [
    'AWSDeployer',

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


@command(env=True)
def push_uwsgi_config(config):
    template = '{remote.uwsgi.config_file}'
    destination = '/etc/uwsgi/{package}.ini'
    copy_file(config, template, destination, template=True, sudo=True)


@command(env=True)
def restart_uwsgi(config):
    """Restart the app's uWSGI process."""
    remote(config, 'touch /etc/uwsgi/{package}.ini', sudo=True)
