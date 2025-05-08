#!/usr/bin/env python3
# YAML configuration file parsing

import yaml
from utils.logging import log
from utils import secrets
from sys import exit

def parse_repos_to_convert_file(repos_to_convert_file_path):
    """Load and parse YAML configuration file."""

    repos_to_convert_dict = {}

    # Parse the repos-to-convert.yaml file
    try:

        # Open the file
        with open(repos_to_convert_file_path, "r") as repos_to_convert_file:

            # This should return a dict
            repos_to_convert_dict = yaml.safe_load(repos_to_convert_file)

    except FileNotFoundError:

        log(f"repos-to-convert.yaml file not found at {repos_to_convert_file_path}", "error")
        exit(1)

    except (AttributeError, yaml.scanner.ScannerError) as exception:

        log(f"Invalid YAML file format in {repos_to_convert_file_path}, please check the structure matches the format in the README.md. Exception: {type(exception)}, {exception.args}, {exception}", "error")
        exit(2)

    repos_to_convert_dict = sanitize_repos_to_convert(repos_to_convert_dict)

    log(f"Parsed {len(repos_to_convert_dict)} repos from {repos_to_convert_file_path}", "info")
    log(f"Repos to convert: {repos_to_convert_dict}", "debug")


    return repos_to_convert_dict


def sanitize_repos_to_convert(input_value, input_key="", recursed=False):
    """Sanitize inputs to ensure they are the correct type."""

    # Uses recursion to depth-first-search through the repos_dict dictionary, with arbitrary depths, keys, and value types

    # log(f"sanitize_repos_to_convert; starting; type(input_key): {type(input_key)}, input_key: {input_key}, type(input_value): {type(input_value)}, input_value: {input_value}, recursed: {recursed}", "info")

    # Take in the repos_dict
    # DFS traverse the dictionary
    # Get the key:value pairs
    # Convert the keys to strings
    # Validate / convert the value types

    # The inputs that have specific type requirements
    # Dictionary of tuples
    input_value_types_dict = {}
    input_value_types_dict[ "authors-file-path"     ] = (str,           )
    input_value_types_dict[ "authors-prog-path"     ] = (str,           )
    input_value_types_dict[ "bare-clone"            ] = (bool,          )
    input_value_types_dict[ "branches"              ] = (str, list      )
    input_value_types_dict[ "code-host-name"        ] = (str,           )
    input_value_types_dict[ "fetch-batch-size"      ] = (int,           )
    input_value_types_dict[ "git-default-branch"    ] = (str,           )
    input_value_types_dict[ "git-ignore-file-path"  ] = (str,           )
    input_value_types_dict[ "git-org-name"          ] = (str,           )
    input_value_types_dict[ "layout"                ] = (str,           )
    input_value_types_dict[ "password"              ] = (str,           )
    input_value_types_dict[ "svn-repo-code-root"    ] = (str,           )
    input_value_types_dict[ "tags"                  ] = (str, list      )
    input_value_types_dict[ "trunk"                 ] = (str,           )
    input_value_types_dict[ "type"                  ] = (str,           )
    input_value_types_dict[ "username"              ] = (str,           )


    if isinstance(input_value, dict):

        # log(f"sanitize_repos_to_convert(): received dict with key: {input_key} and dict: {input_value}", "info")

        output = {}

        for input_value_key in input_value.keys():

            # log(f"sanitize_repos_to_convert(): key   type: {type(input_key)}; key: {input_key}", "info")
            # log(f"sanitize_repos_to_convert(): value type: {type(input[input_key])}; value: {input[input_key]}", "info")

            # Convert the key to a string
            output_key = str(input_value_key)

            # Recurse back into this function to handle the values of this dict
            output[output_key] = sanitize_repos_to_convert(input_value[input_value_key], input_value_key, True)

    # If this function was called with a list
    elif isinstance(input_value, list):

        # log(f"sanitize_repos_to_convert(): received list with key: {input_key} and list: {input_value}", "info")

        output = []

        for input_list_item in input_value:

            # log(f"sanitize_repos_to_convert(): type(input_list_item): {type(input_list_item)}; input_list_item: {input_list_item}", "info")

            # Recurse back into this function to handle the values of this list
            output.append(sanitize_repos_to_convert(input_list_item, input_key, True))

    else:

        # If the key is in the input_value_types_dict, then validate the value type
        if input_key in input_value_types_dict.keys():

            # If the value's type is in the tuple, then just copy it as is
            if type(input_value) in input_value_types_dict[input_key]:

                output = input_value

            # Type doesn't match
            else:

                # Construct the warning message
                type_warning_message = f"Parsing REPOS_TO_CONVERT file found incorrect variable type for "

                if input_key == "password":
                    type_warning_message += input_key
                else:
                    type_warning_message += f"{input_key}: {input_value}"

                type_warning_message += f", type {type(input_value)}, should be "

                for variable_type in input_value_types_dict[input_key]:
                    type_warning_message += f"{variable_type}, "

                type_warning_message += "will attempt to convert it"

                # Log the warning message
                log(type_warning_message, "warning")

                # Cast the value to the correct type
                # This one chokes pretty hard, need to add a try except block
                # ValueError: invalid literal for int() with base 10: '2=1'
                if input_value_types_dict[input_key] == (int,):
                    output = int(input_value)

                elif input_value_types_dict[input_key] == (bool,):
                    output = bool(input_value)

                else:
                    output = str(input_value)
                    # log(f"output = str(input_value): {output}", "info")

            # Now that the keys and values are the correct type, check if it's a password
            if input_key == "password":

                # Add the password value to the passwords set, to be redacted from logs later
                secrets.add(input_value)

        else:

            log(f"No type check for {input_key}: {input_value} variable in REPOS_TO_CONVERT file", "warning")
            output = input_value

    # log(f"sanitize_repos_to_convert; ending; type(output): {type(output)}, output: {output}", "info")
    return output
