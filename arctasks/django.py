from invoke.tasks import ctask as task

from .config import configured
from .runners import local


@task(configured)
def manage(ctx, args, cd=None, sudo=False, run_as=None, echo=True, hide=False,
           abort_on_failure=True):
    """Run a Django management command."""
    local(ctx, ('{python}', 'manage.py', args), cd, sudo, run_as, echo, hide, abort_on_failure)
