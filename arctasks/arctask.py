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
    - Default task options can be overridden by adding config items with
      names like ``package.module.task_name.option_name``.

Note: The name of this module is "arctask" instead of just "task"
because the latter causes Invoke to choke for some reason.

"""
import os
import time

from invoke.context import Context
from invoke.tasks import Task as BaseTask

from .util import abort, print_info


DEFAULT_ENV = object()


class Task(BaseTask):

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
                elif self.configured is DEFAULT_ENV:
                    env = os.environ.get('ARCTASKS_DEFAULT_ENV', 'dev')
                else:
                    env = self.configured
                configure(ctx, env)

            # Fill in options from config. For each option that is not
            # passed on the command line, this looks for a default value
            # for the option in the config. Positional args are skipped.
            #
            # NOTE: At this point, Invoke's machinery has already filled
            #       in all the options based on defaults (i.e., task
            #       keyword args) and command line args. In the super
            #       __call__ method, the wrapped task is called directly
            #       with the options.
            config = ctx['__config__']
            for argument in self.get_arguments():
                # XXX: Checking the argument value here doesn't tell us
                #      what we need to know: whether the argument was
                #      set explicitly via the command line. The end
                #      result is that if an option is set in the config,
                #      that value will *always* be used. Currently, I'm
                #      not sure of a good way to fix this. Generally, if
                #      an option is set in the config, it won't need to
                #      be set on the command line, so this isn't a HUGE
                #      problem.
                if argument._value is None and not argument.positional:
                    name = argument.name
                    path = self.get_option_path(name)
                    if path in config:
                        options[name] = config[path]

        if self.timed:
            start_time = time.monotonic()

        result = super().__call__(ctx, *args, **options)

        if self.timed:
            self.print_elapsed_time(time.monotonic() - start_time)

        return result

    def get_option_path(self, name):
        """Get path to option in task config for this task.

        Args:
            name: Corresponds to a task option

        Returns:
            path: Path to option, constructed from module path, task
                name, and option name

        As an example, let's say this ``Task`` wraps the
        ``build_static`` task. ``build_static`` is defined in the
        ``arctasks.static`` module. Say we want the path to its
        ``optimize`` option::

            self.option_path('optimize')
            # -> 'arctasks.static.build_static.optimize'

        """
        return '.'.join((self.body.__module__, self.body.__qualname__, name))

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
