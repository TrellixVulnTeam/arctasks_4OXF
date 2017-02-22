# ARC Tasks

This package implements common tasks for ARC Django projects.

The tasks in this package have been extracted from various other ARC projects,
cleaned up, generalized, and made more configurable. The lineage is `rethink`
=> `ohslib` => `neighborhoodpulse` => `arctasks`.

## Using ARC Tasks in a Project

- Add `psu.oit.arc.tasks` to the project's requirements

  - Add it to `install_requires` in `setup.py`, if the project has a `setup.py`

  - Add `git+https://github.com/PSU-OIT-ARC/arctasks#egg=psu.oit.arc.tasks`
    to the project's pip requirements file

- Add a `tasks.py` module to the project's top level directory

- Add `from arctasks import *` to `tasks.py`; a default set of tasks is now
  available, which can be listed with `runtasks --list`

- Write the project's `init` task in `tasks.py`; here's a simple example (all
  of the tasks used in this `init` task are provided by ARC Tasks):

        @task(default_env='dev', timed=True)
        def init(config, overwrite=False):
            virtualenv(config, overwrite=overwrite)
            install(config)  # Does `pip install -r requirements.txt` by default
            createdb(config, drop=overwrite)  # Creates a Postgres DB by default
            migrate(config)
            test(config, keepdb=False)

- Run `run init`
