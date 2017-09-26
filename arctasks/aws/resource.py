import os.path
import shutil

from runcommands import command
from runcommands.util import abort, confirm
from runcommands.commands import local

from ..util import abs_path


__all__ = [
    'create_application_stack',
    'add_resource_to_stack'
]


def _render_template(config, template, destination=None):
    template_path = abs_path(template, format_kwargs=config)
    with open(template_path) as tpl:
        contents = tpl.read()
        output = contents.format_map(config)

    if destination is not None:
        with open(destination, 'w') as dest:
            dest.write(output)
        return None

    return output


def _get_stack_name(config):
    return 'app-{env}.template.yml'.format_map(config)


@command(env=True)
def create_application_stack(config):
    if not os.path.exists('cloudformation'):
        local(config, ('mkdir', 'cloudformation'))

    template_name = _get_stack_name(config)
    stack_path = os.path.join('cloudformation', template_name)
    _render_template(config,
                     'arctasks.aws:templates/cloudformation/app.template.yml',
                     destination=stack_path)


@command(env=True)
def add_resource_to_stack(config, resource_name):
    template_name = _get_stack_name(config)
    stack_path = os.path.join('cloudformation', template_name)
    if not os.path.exists(stack_path):
        abort(message="Application stack does not exist.")

    with open(stack_path, 'a') as stack:
        resource_path = 'arctasks.aws:templates/cloudformation/{resource_name}.template.yml'
        stack.write(_render_template(config, resource_path.format(resource_name=resource_name)))


@command(env=True)
def spawn_resources(config):
    template_name = _get_stack_name(config)
    stack_path = os.path.join('cloudformation', template_name)
    if not os.path.exists(stack_path):
        abort(message="Application stack does not exist.")

    stack_name = '{package}-{env}'.format(package=config.package[:10], env=config.env)
    local(config, (
        '{venv}/bin/aws',
        'cloudformation',
        'create-stack',
        '--stack-name',
        stack_name,
        '--template-body',
        'file://{}'.format(stack_path),
        '--capabilities',
        'CAPABILITY_NAMED_IAM'
    ))
