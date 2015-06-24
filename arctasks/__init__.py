from invoke.tasks import ctask as task
from .base import clean, install, virtualenv
from .config import configure, configured, show_config, dev, stage, prod
from .db import createdb
from .deploy import builds, deploy, link, restart
from .django import manage, makemigrations, migrate, test
from .runners import local, remote
from .static import build_static, bower, lessc
