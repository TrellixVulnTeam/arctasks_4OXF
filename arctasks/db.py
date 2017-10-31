import os
from getpass import getpass
from tempfile import mkstemp

from runcommands import command
from runcommands.config import Config
from runcommands.commands import local
from runcommands.util import abort, confirm


@command(default_env='dev')
def load_prod_data(config,
                   reset=False,
                   source='prod', source_user=None, source_host=None, source_port=None,
                   source_name=None,
                   user='{db.user}', host='{db.host}', port='{db.port}', name='{db.name}',
                   schema='public'):
    """Load data from prod database directly into env database.

    This is generally intended for fetching a fresh copy of production
    data into the dev database. As such, this will typically be run like
    so::

        run createdb -d load_prod_data

    You can also choose another data source, such as 'stage'::

        run createdb -d load_prod_data --source stage

    To refresh the stage database, you'd run this instead::

        run stage reset_db load_prod_data

    """
    if config.env == 'prod':
        abort(1, 'Cannot load data into prod database')

    if config.env == source:
        abort(1, 'Cannot load data into source database')

    if reset:
        reset_db(config, user, host, port, name)

    run_config = config.run.copy()
    run_config.env = source
    source_config = Config(run=run_config)
    source_pw = getpass('{source} database password: '.format_map(locals()))
    env_pw = getpass('{env} database password: '.format_map(config))
    temp_fd, temp_path = mkstemp()

    if config.db.type == 'postgresql':
        if source_pw:
            os.environ['PGPASSWORD'] = source_pw

        local(config, (
            'pg_dump',
            '--format', 'custom',
            '-U', source_user or source_config.db.user,
            '-h', source_host or source_config.db.host,
            '-p', source_port or source_config.db.port,
            '-d', source_name or source_config.db.name,
            '--schema', schema,
            '--blobs',
            '--no-acl',
            '--no-owner',
            '--no-privileges',
            '--file', temp_path,
        ))

        if env_pw:
            os.environ['PGPASSWORD'] = env_pw

        local(config, (
            'pg_restore',
            '-U', user,
            '-h', host,
            '-p', port,
            '-d', name,
            '--no-owner',
            temp_path,
        ))

        os.close(temp_fd)
        os.remove(temp_path)
    elif config.db.type == 'mysql':
        raise NotImplementedError('load_prod_data not yet implemented for MySQL')
    else:
        raise ValueError('Unknown database type: {db.type}'.format_map(config))


@command(default_env='dev')
def reset_db(config, user='{db.user}', host='{db.host}', port='{db.port}', name='{db.name}',
             truncate=False):
    """DROP CASCADE tables in database.

    This drops all tables owned by the app user in the public schema
    except for PostGIS tables.

    This is mainly intended to clear out the stage database during the
    early stages of development when there may be a lot of schema churn
    or test data. You'd run this and then reapply migrations to get a
    nice clean database.

    Another option is to TRUNCATE tables instead of dropping them. You
    might use this option if you want to load some new data.

    This can also be run in dev, and other non-prod environments. It
    cannot be run in prod.

    """
    if config.env == 'prod':
        abort(1, 'reset_db cannot be run on the prod database')

    user = user.format_map(config)
    host = host.format_map(config)
    port = port.format_map(config)
    name = name.format_map(config)
    op = 'TRUNCATE' if truncate else 'DROP'

    msg = (
        'Do you really want to reset the {{env}} database ({user}@{host}:{port}/{name})?\n'
        'This will {op} CASCADE all tables (excluding PostGIS tables).'.format_map(locals()))
    if not confirm(config, msg):
        abort(0)

    password = getpass('{env} database password: '.format_map(config))
    if password:
        os.environ['PGPASSWORD'] = password

    psql = ('psql', '-U', user, '-h', host, '-p', port, '-d', name)

    result = local(config, (
        psql, '--tuples-only --command "',
        "SELECT tablename "
        "FROM pg_tables "
        "WHERE schemaname = 'public' "
        "AND tableowner = '" + user + "' "
        "AND tablename NOT IN ('geography_columns', 'geometry_columns', 'spatial_ref_sys');",
        '"',
    ), hide='stdout', use_pty=False)

    tables = sorted(s.strip() for s in result.stdout.strip().splitlines())
    if not tables:
        abort(1, 'No tables found to drop')

    statements = ['{op} TABLE "{table}" CASCADE;'.format(op=op, table=table) for table in tables]

    print('\nThe following statements will be run:\n')
    print('    {statements}\n'.format(statements='\n    '.join(statements)))

    confirmation_message = 'Are you sure you want to do this (you must type out "yes")?'
    confirmed = confirm(config, confirmation_message, yes_values=('yes',))

    if confirmed:
        local(config, (psql, '-c "', statements, '"'))
    else:
        print('Cancelled')
