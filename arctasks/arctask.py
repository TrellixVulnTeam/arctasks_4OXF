"""Provides the @arctask decorator.

``@arctask`` is essentially an enhanced version of Invoke's ``@ctask``.
Its main features are:

    - Tasks are contextualized by default
    - Tasks can be automatically configured using the ``configured``
      arg; this can be used to specify the default environment to
      configure the task for (by specifying the env name), or it can be
      used to specify a task must be explicitly configured (by passing
      ``True``)
    - Tasks can be timed using the ``timed`` arg
    - Tasks can have default option values specified via config. To do
      this, set the option's value to ``None`` in the task def and then
      add a config item named ``package.module.task_name.option_name``
      with the default value.

Note: The name of this module is "arctask" instead of just "task"
because the latter causes Invoke to choke for some reason.

"""
import time

from invoke.context import Context
from invoke.tasks import Task as BaseTask

from .util import abort, print_info


class Task(BaseTask):

    default_env = 'dev'

    def __init__(self, *args, configured=False, timed=False, **kwargs):
        self.configured = configured
        self.timed = timed
        kwargs.setdefault('contextualized', True)
        super().__init__(*args, **kwargs)

    def __call__(self, ctx, *args, **options):
        assert isinstance(ctx, Context), 'This task must be called with a Context'

        if self.configured:
            if not ctx.get('__configured__'):
                if self.configured is True:
                    abort(1, 'You must explicitly configure the {0.__name__} task'.format(self))
                elif isinstance(self.configured, str):
                    env = self.configured
                configure(ctx, env)

            # Fill in options from config. For each option that is not
            # present or is None, this looks for a default value for the
            # option in the config. This skips positional args
            config = ctx['__config__']
            for argument in self.get_arguments():
                name = argument.name
                if not argument.positional and options.get(name) is None:
                    path = '.'.join((self.body.__module__, self.body.__qualname__, name))
                    if path in config:
                        options[name] = config[path]

        if self.timed:
            start_time = time.monotonic()

        result = super().__call__(ctx, *args, **options)

        if self.timed:
            self.print_elapsed_time(time.monotonic() - start_time)

        return result

    def print_elapsed_time(self, elapsed_time):
        m, s = divmod(elapsed_time, 60)
        m = int(m)
        print_info('Elapsed time for {self.__name__} task: {m:d}m {s:.3f}s'.format(**locals()))


def arctask(*args, **kwargs):
    if len(args) == 1 and callable(args[0]) and not isinstance(args[0], BaseTask):
        return Task(args[0], **kwargs)
    if args:
        assert 'pre' not in kwargs, 'Pass pre tasks as args OR via kwargs but not both'
        kwargs['pre'] = args
    return lambda fn: Task(fn, **kwargs)


# Avoid circular import
from arctasks.config import configure
