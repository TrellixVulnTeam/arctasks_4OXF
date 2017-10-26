import configparser
import os.path

from arctasks.util import abs_path

from .config import RESOURCE_SECRETS


def render_template(config, template, destination=None):
    template_path = abs_path(template, format_kwargs=config)
    with open(template_path) as tpl:
        contents = tpl.read()
        output = contents.format_map(config)

    if destination is not None:
        with open(destination, 'w') as dest:
            dest.write(output)
        return None

    return output


def get_stack_file(config):
    return 'app-{env}.template.yml'.format_map(config)


def get_stack_name(config):
    return '{}-{}'.format(config.package[:10], config.env)


def get_resource_in_stack(config, client, resource):
    stack_payload = client.describe_stack_resources(
        StackName=get_stack_name(config),
        LogicalResourceId=resource
    )
    return (stack_payload['StackResources'], stack_payload)


def replace_stack_parameters(stack_path, params, values):
    with open(stack_path, 'r') as f:
        stack_definition = f.read()
    for idx, param in enumerate(params):
        stack_definition = stack_definition.replace(
            '{}: {}'.format(param, values[idx][0]),
            '{}: {}'.format(param, values[idx][1])
        )
    with open(stack_path, 'w') as f:
        f.write(stack_definition)


# YAML-formatted data as parameters payload is currently unsupported.
# Ref: https://github.com/aws/aws-cli/issues/2275
def get_parameters_file(config):
    return '.app-{env}.parameters'.format_map(config)


# TODO: If it is deemed useful, implement support for interactive
#       input of secret values.
def update_parameters_file(config, resource_name):
    parameters_file = get_parameters_file(config)
    parameters_path = os.path.join('cloudformation', parameters_file)

    with open(parameters_path, 'a') as f:
        for param, func in RESOURCE_SECRETS[resource_name]:
            print("Generating secret for '{}'".format(param))
            f.write('{}:{}\n'.format(param, func()))


def get_parameters_prefix(config):
    return '{}/{}'.format(config.infrastructure.vpc_stack_name, config.package)
