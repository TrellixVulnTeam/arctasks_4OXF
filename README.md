# ARC Tasks

This package implements common tasks for ARC Django projects. Tasks are
implemented using [Invoke](http://www.pyinvoke.org/).

The tasks in this package have been extracted from various other ARC projects,
cleaned up, generalized, and made more configurable. The lineage is `rethink`
=> `ohslib` => `neighborhoodpulse` => `arctasks`.

## Using ARC Tasks in a Project

- Add `psu.oit.arc.tasks` to the project's requirements

  - Add it to `install_requires` in `setup.py`, if the project has a `setup.py`

  - Add `-e git+https://github.com/PSU-OIT-ARC/arctasks#egg=psu.oit.arc.tasks`
    to the project's pip requirements file

- Add a `tasks.py` module to the project's top level directory

- Add `from arctasks import *` to `tasks.py`; a default set of tasks is now
  available, which can be listed with `inv --list`

- Write the project's `init` task in `tasks.py`; here's a simple example (all
  of the tasks used in this `init` task are provided by ARC Tasks):

        @arctask(configured='dev', timed=True)
        def init(ctx, overwrite=False):
            virtualenv(ctx, overwrite=overwrite)
            install(ctx)  # Does `pip install -r requirements.txt` by default
            createdb(ctx, drop=overwrite)  # Creates a Postgres DB by default
            migrate(ctx)
            test(ctx, keepdb=False)

- Run `inv init`
