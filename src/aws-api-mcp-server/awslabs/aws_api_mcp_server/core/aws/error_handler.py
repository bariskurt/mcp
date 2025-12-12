import re
import json
from loguru import logger
from pathlib import Path
from awscli.clidriver import ServiceCommand
from awscli.customizations.commands import BasicCommand
from typing import Any
from awscli.bcdoc.restdoc import ReSTDocument
from .services import get_awscli_driver

IGNORED_ARGUMENTS = frozenset({'cli-input-json', 'generate-cli-skeleton'})

EXAMPLES_FILE = Path.home().resolve() / ".config" / "aws-api-mcp-server" / "api_examples.jsonl"
ADD_DOCUMENTATION = False
ADD_EXAMPLES = True


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


def build_examplelookup():    
    examples_lookup = {}
    with open(EXAMPLES_FILE, 'r') as f:
        for line in f:
            try:
                api_example = json.loads(line)
                examples_lookup[api_example["command"]] = api_example["examples"]
            except json.JSONDecodeError:
                logger.info(f"Skipping invalid JSON line: {line}")
    return examples_lookup


def get_examples(service_name: str, operation_name: str) -> dict[str, Any]:
    try:
        examples_lookup = build_examplelookup()        
    except Exception as e:
        raise Exception(f"Cannot load API examples file: {str(e)}")
    
    examples = examples_lookup.get(f"aws {service_name} {operation_name}")
    if not examples:
        raise Exception(f"No examples found for {service_name}.{operation_name}")
    
    return examples


def add_documentation(service_name: str, operation_name: str, error_message: str) -> str:
    try:
        description, params = get_api_schema(service_name, operation_name)
        helper_documentation = {
            "documentation": {
                "service": service_name,
                "operation": operation_name,
                "description": description,
                "parameters": params
            }
        }
        return error_message + "\n" + json.dumps(helper_documentation, indent=4)
        
    except Exception as e:        
        logger.info(f"API schema extraction error: {e}")
    
    return error_message


def add_examples(service_name: str, operation_name: str, error_message: str) -> str:
    try:
        examples = get_examples(service_name, operation_name)        
        return error_message + " Here are examples for the correct usage of this command: " + json.dumps(examples)
    except Exception as e:        
        logger.info(f"API example extraction error: {e}")
    
    return error_message


def with_api_schema(cli_command: str, error_message: str) -> str:

    if not (ADD_DOCUMENTATION or ADD_EXAMPLES):
        logger.info(f"Validation error helper is disabled.")
        return error_message

    parts = cli_command.split(' ')
    if parts[0] != 'aws':
        logger.info(f"Not a valid AWS CLI, skip API schema extraction.")
        return error_message

    service_name, operation_name = parts[1], parts[2]
    logger.info(f"Extracing API schema for service: {service_name}, operation: {operation_name}")

    if ADD_DOCUMENTATION:
        error_message = add_documentation(service_name, operation_name, error_message)
    
    if ADD_EXAMPLES:
        error_message = add_examples(service_name, operation_name, error_message)

    return error_message
