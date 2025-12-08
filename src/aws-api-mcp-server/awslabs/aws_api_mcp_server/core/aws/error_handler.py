import re
import json
from loguru import logger

from awscli.clidriver import ServiceCommand
from awscli.customizations.commands import BasicCommand
from typing import Any
from awscli.bcdoc.restdoc import ReSTDocument
from .services import get_awscli_driver

IGNORED_ARGUMENTS = frozenset({'cli-input-json', 'generate-cli-skeleton'})

ENABLE_VALIDATION_ERROR_HELPER = False


driver = get_awscli_driver()

def _clean_text(text: str) -> str:
    text = re.sub(r'\s+', ' ', text)  # Normalize whitespace
    return text.strip()


def _clean_description(description: str) -> str:
    """This removes the section title added by the help event handlers."""
    description = re.sub(r'=+\s*Description\s*=+\s', '', description)
    return _clean_text(description)


def _generate_operation_document(operation: Any) -> dict[str, Any]:
    """Generate a document for a single AWS API operation."""
    help_command = operation.create_help_command()
    event_handler = help_command.EventHandlerClass(help_command)

    # Get description
    event_handler.doc_description(help_command)
    description = _clean_description(help_command.doc.getvalue().decode('utf-8')).strip()

    # Get parameters
    params = {}
    seen_arg_groups = set()
    for arg_name, arg in help_command.arg_table.items():
        if getattr(arg, '_UNDOCUMENTED', False) or arg_name in IGNORED_ARGUMENTS:
            continue
        if arg.group_name in seen_arg_groups:
            continue
        help_command.doc = ReSTDocument()
        if hasattr(event_handler, 'doc'):
            event_handler.doc = help_command.doc
        event_handler.doc_option(help_command=help_command, arg_name=arg_name)
        key = arg.group_name if arg.group_name else arg_name
        params[key] = _clean_text(help_command.doc.getvalue().decode('utf-8').strip())
        if arg.group_name:
            # To avoid adding arguments like --disable-rollback and --no-disable-rollback separately
            # we need to make sure a group name is only processed once
            # event_handler.doc_option takes care of mentioning all arguments in a group
            # so we can safely skip the remaining arguments in the group
            seen_arg_groups.add(arg.group_name)

    return description, params


def get_api_schema(service_name: str, operation_name: str):

    command = driver._get_command_table().get(service_name)

    if isinstance(command, BasicCommand):
        print("Basic")
        command_table = command.subcommand_table
    elif isinstance(command, ServiceCommand):
        print("Service")
        command_table = command._get_command_table()
    else:
        logger.info(f"Unknown command type: {type(command)}")
    operation = command_table[operation_name]

    return _generate_operation_document(operation)


def with_api_schema(cli_command: str, error_message: str) -> str:

    if not ENABLE_VALIDATION_ERROR_HELPER:
        logger.info(f"Validation error helper is disabled.")
        return error_message

    parts = cli_command.split(' ')
    if parts[0] != 'aws':
        logger.info(f"Not a valid AWS CLI, skip API schema extraction.")
        return error_message

    service_name, operation_name = parts[1], parts[2]
    logger.info(f"Extracing API schema for service: {service_name}, operation: {operation_name}")

    try:
        description, params = get_api_schema(service_name, operation_name)
    except Exception as e:        
        logger.info(f"API schema extraction error: {e}")
        return error_message
    
    helper_documentation = {
        "documentation": {
            "service": service_name,
            "operation": operation_name,
            "description": description,
            "parameters": params
        }
    }

    return error_message + "\n" + json.dumps(helper_documentation, indent=4)
