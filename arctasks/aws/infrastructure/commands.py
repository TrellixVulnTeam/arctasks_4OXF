import os.path

import boto3

from runcommands import command
from runcommands.util import abort, confirm
from runcommands.commands import local
from runcommands.config import ConfigParser, RunConfig, Config

from .config import RESOURCE_PARAMETERS, RESOURCE_SECRETS
from . import utils


@command(env=True)
def create_application_stack(config):
    if not os.path.exists('cloudformation'):
        local(config, ('mkdir', 'cloudformation'))

    template_name = utils.get_stack_file(config)
    stack_path = os.path.join('cloudformation', template_name)
    utils.render_template(config,
                     'arctasks.aws:templates/cloudformation/app.template.yml',
                     destination=stack_path)

    # generate secrets required by application
    utils.update_parameters_file(config, 'app')


# TODO: Add special case for handling ELB listener priority: query current value
#       and increment queried value into template.
@command(env=True)
def add_resource_to_stack(config, resource_name):
    template_name = utils.get_stack_file(config)
    stack_path = os.path.join('cloudformation', template_name)
    if not os.path.exists(stack_path):
        abort(message="Application stack does not exist.")

    with open(stack_path, 'a') as stack:
        resource_path = 'arctasks.aws:templates/cloudformation/{resource_name}.template.yml'
        stack.write(utils.render_template(config,
                                          resource_path.format(resource_name=resource_name)))

    # generate secrets required by resource
    if resource_name in RESOURCE_SECRETS:
        utils.update_parameters_file(config, resource_name)


@command(env=True)
def spawn_resources(config):
    stack_path = os.path.join('cloudformation', utils.get_stack_file(config))
    if not os.path.exists(stack_path):
        abort(message="Application stack does not exist.")

    parameters_path = os.path.join('cloudformation', utils.get_parameters_file(config))
    if os.path.exists(parameters_path):
        (params, values) = ([], [])
        with open(parameters_path, 'r') as f:
            for param in f.readlines():
                (key, value) = param.strip().split(':')
                params.append(key)
                values.append(('__SECRET__', value))
        print("Substituting generated secrets...")
        utils.replace_stack_parameters(stack_path, params, values)

    client = boto3.client('cloudformation')
    with open(stack_path, 'r') as f:
        stack_name = utils.get_stack_name(config)
        print("Creating stack '{}'".format(stack_name))
        client.create_stack(StackName=stack_name,
                            TemplateBody=f.read(),
                            Capabilities=['CAPABILITY_NAMED_IAM'])

    if os.path.exists(parameters_path):
        print("Created resources with secret parameters from '{}'".format(parameters_path))
        print("Use the 'create-ssm-parameters' command to publish secrets to the parameter store.")


@command(env=True)
def create_ssm_parameters(config):
    stack_path = os.path.join('cloudformation', utils.get_stack_file(config))
    if not os.path.exists(stack_path):
        abort(message="Application stack '{}' does not exist.".format(stack_path))

    parameters_path = os.path.join('cloudformation', utils.get_parameters_file(config))
    if not os.path.exists(parameters_path):
        abort(message="Parameters file '{}' does not exist.".format(parameters_path))

    print("Exporting secrets from '{}' to SSM parameter store.".format(parameters_path))
    if not confirm(config, "Confirm that the instance key has been created."):
        return

    parameters_prefix = utils.get_parameters_prefix(config)
    key_id = 'alias/{}'.format(parameters_prefix)
    (params, values) = ([], [])

    with open(parameters_path, 'r') as f:
        client = boto3.client('ssm')
        for line in f.readlines():
            (key, value) = line.strip().split(':')
            client.put_parameter(Type='SecureString',
                                 KeyId=key_id,
                                 Name='/{}/{}'.format(parameters_prefix, key),
                                 Value=value,
                                 Overwrite=True)
            params.append(key)
            values.append((value, '__SECRET__'))

    print("Scrubbing secrets...")
    utils.replace_stack_parameters(stack_path, params, values)
    print("Removing parameters file...")
    os.remove(parameters_path)


@command(env=True)
def add_resource_configuration(config):
    command_config = ConfigParser()
    with open('commands.cfg', 'r') as f:
        command_config.read_file(f)

    if config.env not in command_config.sections():
        command_config.add_section(config.env)

    parameters_prefix = utils.get_parameters_prefix(config)
    command_config.set(config.env, 'ssm.prefix', '"{}"'.format(parameters_prefix))

    client = boto3.client('cloudformation')
    for resource, parameters in RESOURCE_PARAMETERS['commands'].items():
        (has_resource, stack_payload) = utils.get_resource_in_stack(config, client, resource)
        if not has_resource:
            print("Resource '{}' not present. Skipping.".format(resource))
            continue
        stack_name = stack_payload['StackResources'][0]['PhysicalResourceId']
        resource_payload = client.describe_stacks(StackName=stack_name)
        for output_info in resource_payload['Stacks'][0]['Outputs']:
            if output_info['OutputKey'] in parameters.keys():
                command_config.set(config.env,
                                   parameters[output_info['OutputKey']],
                                   '"{}"'.format(output_info['OutputValue']))

    with open('commands.cfg', 'w') as f:
        command_config.write(f)
    print("Wrote updated 'commands.cfg'.")

    # reload 'config' from (possibly) updated configuration file
    config = Config(run=RunConfig(config_file='commands.cfg',
                                  env=config.env))

    app_base_config_path = 'local.base.cfg'
    if not os.path.exists(app_base_config_path):
        print("No local configuration found. Skipping app configuration.")
        return

    app_config_path = 'local.{}.cfg'.format(config.env)
    if not os.path.exists(app_config_path):
        with open(app_config_path, 'w') as f:
            f.write("[{}]\n".format(config.env))
            f.write("extends = \"local.base.cfg\"")

    app_config = ConfigParser()
    with open(app_config_path, 'r') as f:
        app_config.read_file(f)

    # fill in app configuration
    parameters_prefix = utils.get_parameters_prefix(config)
    app_config.set(config.env, 'AWS_REGION', '"{}"'.format(config.infrastructure.region))
    app_config.set(config.env, 'SSM_KEY', '"{}"'.format(parameters_prefix))
    app_config.set(config.env, 'SECRET_KEY', '""')

    def get_config_value(key):
        if key is None or not key:
            return ''
        value = config
        for part in key.split('.'):
            value = getattr(value, part)
        return value

    for resource, parameters in RESOURCE_PARAMETERS['app'].items():
        (has_resource, stack_payload) = utils.get_resource_in_stack(config, client, resource)
        if not has_resource and resource != 'Default':
            print("Resource '{}' not present. Skipping.".format(resource))
            continue
        for key, value in parameters.items():
            config_value = get_config_value(value)
            if isinstance(config_value, list):
                app_config.set(config.env, key, "{}".format(config_value))
            else:
                app_config.set(config.env, key, '"{}"'.format(config_value))

    with open(app_config_path, 'w') as f:
        app_config.write(f)
    print("Wrote updated '{}'.".format(app_config_path))
