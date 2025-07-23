#!/usr/bin/env python3
# Parse YAML configuration file

# Import repo-converter modules
from utils import secret
from utils.context import Context
from utils.log import log

# Import Python standard modules
from sys import exit
from urllib.parse import urlparse
import json

# Import third party modules
import yaml # https://pyyaml.org/wiki/PyYAMLDocumentation


def load_from_file(ctx: Context) -> None:
    """Load and parse YAML configuration file"""

    repos_to_convert_file_path = ctx.env_vars["REPOS_TO_CONVERT"]
    repos = {}

    # Parse the file
    try:

        # Open the file
        with open(repos_to_convert_file_path, "r") as repos_to_convert_file:

            # This should return a dict
            repos = yaml.safe_load(repos_to_convert_file)

    except IsADirectoryError:

        log(ctx, f"File not found at {repos_to_convert_file_path}, but found a directory, likely created by the Docker mount. Please stop the container, delete the directory, and create the yaml file.", "critical")
        exit(1)

    except FileNotFoundError:

        log(ctx, f"File not found at {repos_to_convert_file_path}", "critical")
        exit(2)

    except (AttributeError, yaml.scanner.ScannerError) as exception: # type: ignore

        log(ctx, f"YAML syntax error in {repos_to_convert_file_path}, please lint it. Exception: {type(exception)}, {exception.args}, {exception}", "critical")
        exit(3)

    repos = check_types(ctx, repos)
    repos = reformat_repos_dict(ctx, repos)
    repos = sanitize_inputs(ctx, repos)
    repos = validate_inputs(ctx, repos)
    repos = validate_required_inputs(ctx, repos)

    ctx.repos = repos

    # log(ctx, f"Parsed {len(ctx.repos)} repos from {repos_to_convert_file_path}", "info")

    repos_to_log = {"repos": ctx.repos}
    log(ctx, "Repos to convert", "debug", repos_to_log)


def check_types(ctx: Context, repos: dict) -> dict:
    """Middle layer function to abstract return type ambiguity"""

    repos = check_types_recursive(ctx, repos)

    # check_types_recursive() uses recursion and can return many different types, but ends with a dict
    return repos


def check_types_recursive(ctx: Context, input_value, input_key="", recursed=False): # -> Any
    """
    Recursive function to sanitize inputs of arbitrary types,
    to ensure they are returned as the correct type.
    """

    # Uses recursion to depth-first-search through the repos dictionary, with arbitrary depths, keys, and value types
    # Take in the repos
    # DFS traverse the dictionary
    # Get the key:value pairs
    # Convert the keys to strings
    # Validate / convert the value types

    # The inputs that have specific type requirements
    # Dictionary of tuples, must have commas in the values set

    repos_to_convert_fields = {}


    # TODO: Implement these
    repos_to_convert_fields[ "max-concurrent-conversions"    ] = (int,           )
    repos_to_convert_fields[ "fetch-interval"                ] = (int,           )
    repos_to_convert_fields[ "commits-to-skip"               ] = (str, list      )

    repos_to_convert_fields[ "default-branch-only"           ] = (bool,          )
    repos_to_convert_fields[ "git-clone-command-args"        ] = (str,           )
    repos_to_convert_fields[ "git-ssh-command-args"          ] = (str,           )
    repos_to_convert_fields[ "tfvc-collection"               ] = (str,           )
    repos_to_convert_fields[ "token"                         ] = (str, "secret"  )
    # repos_to_convert_fields[ "global"                        ] = (dict,          ) # Would like to validate dicts as well


    # TODO: Test these
    repos_to_convert_fields[ "authors-file-path"             ] = (str,           )
    repos_to_convert_fields[ "authors-prog-path"             ] = (str,           )
    repos_to_convert_fields[ "bare-clone"                    ] = (bool,          )
    repos_to_convert_fields[ "branches"                      ] = (str, list      )
    repos_to_convert_fields[ "git-ignore-file-path"          ] = (str,           )
    repos_to_convert_fields[ "log-window-size"               ] = (int,           )
    repos_to_convert_fields[ "repo-url"                      ] = (str,           ) # Required: Either repo-parent-url or repo-url
    repos_to_convert_fields[ "source-repo-name"              ] = (str,           )
    repos_to_convert_fields[ "svn-layout"                    ] = (str, list      )
    repos_to_convert_fields[ "tags"                          ] = (str, list      )
    repos_to_convert_fields[ "trunk"                         ] = (str,           )

    # Implemented and tested
    repos_to_convert_fields[ "code-host-name"                ] = (str,           ) # Recommended but not strictly required
    repos_to_convert_fields[ "fetch-batch-size"              ] = (int,           )
    repos_to_convert_fields[ "git-default-branch"            ] = (str,           )
    repos_to_convert_fields[ "git-org-name"                  ] = (str,           ) # Recommended but not strictly required
    repos_to_convert_fields[ "destination-git-repo-name"     ] = (str,           ) # Recommended but not strictly required
    repos_to_convert_fields[ "password"                      ] = (str, "secret"  )
    repos_to_convert_fields[ "repo-parent-url"               ] = (str,           ) # Required: Either repo-parent-url or repo-url
    repos_to_convert_fields[ "repos"                         ] = (str, list      )
    repos_to_convert_fields[ "svn-repo-code-root"            ] = (str,           )
    repos_to_convert_fields[ "type"                          ] = (str,           )
    repos_to_convert_fields[ "username"                      ] = (str,           )


    if isinstance(input_value, dict):

        output = {}

        for input_value_key in input_value.keys():

            # Convert the key to a string
            output_key = str(input_value_key)

            # Recurse back into this function to handle the values of this dict
            output[output_key] = check_types_recursive(ctx, input_value[input_value_key], input_value_key, True)

    # If this function was called with a list
    elif isinstance(input_value, list):

        output = []

        for input_list_item in input_value:

            # Recurse back into this function to handle the values of this list
            # This passes in the input_key from the calling function,
            # so that it validates the list items should be the correct type for this list
            output.append(check_types_recursive(ctx, input_list_item, input_key, True))

    else:

        # If the key is in the repos_to_convert_fields, then validate the value type
        if input_key in repos_to_convert_fields.keys():

            # If the value's type is in the tuple, then just copy it as is
            if type(input_value) in repos_to_convert_fields[input_key]:

                output = input_value

            # Type doesn't match
            else:

                # Construct the warning message
                type_warning_message = f"Parsing REPOS_TO_CONVERT file found incorrect variable type for "

                # Set of input keys to not log the values of
                if "secret" in repos_to_convert_fields[input_key]:
                    type_warning_message += input_key
                else:
                    type_warning_message += f"{input_key}: {input_value}"

                type_warning_message += f", type {type(input_value)}, should be "

                for variable_type in repos_to_convert_fields[input_key]:
                    type_warning_message += f"{variable_type}, "

                type_warning_message += "will attempt to convert it"

                # Log the warning message
                log(ctx, type_warning_message, "warning")

                # Cast the value to the correct type
                # This one chokes pretty hard, need to add a try except block
                # ValueError: invalid literal for int() with base 10: '2=1'
                if repos_to_convert_fields[input_key] == (int,):
                    output = int(input_value)

                elif repos_to_convert_fields[input_key] == (bool,):
                    output = bool(input_value)

                else:
                    output = str(input_value)

            # Now that the keys and values are the correct type, check if it's a password
            if "secret" in repos_to_convert_fields[input_key]:

                log(ctx, f"Adding secret {input_key} to set of secrets to redact", "debug")

                # Add the password value to the passwords set, to be redacted from logs later
                secret.add(ctx, input_value)

        else:

            log(ctx, f"No type check for {input_key}: {input_value} variable in REPOS_TO_CONVERT file", "debug")
            output = input_value

    return output


def reformat_repos_dict(ctx: Context, repos_input: dict) -> dict:
    """
    This is the function to make it make sense

    Take the new, more human-intuitive repos-to-convert.yaml schema,
    and convert it into a big, bloated, duplicative, dict of repos,
    to be easily iterated on,

    with hierarchal biases for overlapping configs,
    ex. server config says default-branch-only: false,
    but repo config says default-branch-only: true,
    take the repo config

    """

    repos_to_convert_file_path = ctx.env_vars["REPOS_TO_CONVERT"]

    # TODO: Read dict from creds env var, and add to the repos_dict for all repos in the server they apply to
    # env_credentials = ctx.env_vars["CREDENTIALS"]

    source_repo_types = (
        "git",
        "svn",
        "tfvc",
    )
    repos_output = {}
    repos_global_config = {}

    for server_key in repos_input.keys():

        # Handle the top-level global config key
        if server_key.lower() in ("global", "globals"):
            repos_global_config = repos_input[server_key]
            # log(ctx, f"Found global repo config under {server_key}: {repos_global_config}", "debug")
            continue

        # Otherwise, the top-level keys are code host servers
        server_config_dict = repos_input[server_key]

        # All top level keys should be dicts
        if not isinstance(server_config_dict, dict):
            log(ctx, f"Server {server_key} in {repos_to_convert_file_path} is not a dict, skipping", "error")
            continue

        # If the type key is missing, error, and skip the server
        if (
            "type" not in server_config_dict.keys() or
            len(server_config_dict["type"]) == 0
        ):
            log(ctx, f"Server {server_key} in {repos_to_convert_file_path} has no type field, skipping", "error")
            continue

        repo_type = server_config_dict["type"]

        # If the type key isn't a supported type, error, and skip the server
        if repo_type.lower() not in source_repo_types:
            log(ctx, f"Server {server_key} in {repos_to_convert_file_path} has type: {repo_type}, which is not in the set of supported repo types: {source_repo_types}, skipping", "error")
            continue

        # If the repos key is missing, or has no values, error, and skip the server
        if (
            "repos" not in server_config_dict.keys() or
            len(server_config_dict["repos"]) == 0
        ):
            log(ctx, f"Server {server_key} in {repos_to_convert_file_path} has no repos, skipping", "error")
            continue

        # At this point we know that the repos key exists and has a non-zero length
        repos = server_config_dict["repos"]

        # If the repos key's value's type is a string, then there's only one repo
        if isinstance(repos, str):

            log(ctx, f"Server {server_key} in {repos_to_convert_file_path} has only one repo: {repos}", "debug")

            # But for the sake of DRY code, convert it to a list of one so the next loop can loop through it
            repos = list([repos])

        else:

            # log(ctx, f"Server {server_key} in {repos_to_convert_file_path} has a list of repos: {repos}", "debug")
            pass

        # Okay, at this point, repos should be a list, of strings and / or dicts
        for repo in repos:

            # Assemble the repo_dict item
            # with the repo key as the key
            repo_key = ""
            # and the configs as values
            repo_dict = {}

            # Start with top-level global configs
            for key in repos_global_config.keys():

                # Don't include the global configs under repo types
                if key not in source_repo_types:

                    # Copy the values over
                    repo_dict[key] = repos_global_config[key]

            # Then with global configs for this repo type
            if repo_type in repos_global_config.keys():

                # Copy the keys and values from repos_global_config[repo_type],
                # overwriting any conflicting values from earlier
                repo_dict = repo_dict | repos_global_config[repo_type]

            # Then overwrite with server configs
            for key in server_config_dict.keys():

                # Don't include the repo key
                if key not in ("repos"):

                    # Copy the values over
                    repo_dict[key] = server_config_dict[key]

            # Then overwrite with repo configs
            # If it's just a string, then it doesn't define any repo-specific configs
            if isinstance(repo, str):

                repo_key = repo
                # log(ctx, f"Repo is just a string and doesn't have any config of its own", "debug")

            # If it's a dict, then it does define some repo-specific configs,
            # so grab these repo-specific configs,
            # and overwrite the configs from the parent with these
            if isinstance(repo, dict):

                # TypeError: 'dict_keys' object is not subscriptable
                repo_key = list(repo.keys())[0]

                # Copy the keys and values from repo[repo_key], overwriting any conflicting values from earlier
                if repo[repo_key] is not None:
                    repo_dict = repo_dict | repo[repo_key]

                # log(ctx, f"Repo is a dict, and has some config of its own: {repo[repo_key]}", "debug")


            # If the repo's settings didn't specify a destination-git-repo-name, then assume it from repo_key
            if "destination-git-repo-name" not in repo_dict.keys():
                repo_dict["destination-git-repo-name"] = repo_key

            # If the repo's settings didn't specify a source-repo-name, then assume it from repo_key
            if "source-repo-name" not in repo_dict.keys():
                repo_dict["source-repo-name"] = repo_key

            # Save the repo to the return dict
            repos_output[repo_key] = repo_dict


    # Sort the repos in the dict, and the keys within each repo
    repos_output = dict(sorted(repos_output.items()))
    for repo in repos_output.keys():
        repos_output[repo] = dict(sorted(repos_output[repo].items()))

    return repos_output


def sanitize_inputs(ctx: Context, repos_input: dict) -> dict:
    """
    TODO: Sanitize inputs here
    """

    # Trim trailing '/' from URLs
    url_fields = ctx.url_fields

    for repo in repos_input:

        # Loop through the list
        for url_field in url_fields:

            repo_url = str(repos_input[repo].get(url_field, ""))

            # If this key has a value
            if repo_url:

                # Strip starting and trailing '/'
                repos_input[repo][url_field] = repo_url.strip('/')

    return repos_input


def validate_inputs(ctx: Context, repos_input: dict) -> dict:
    """
    TODO: Add input validation here, ex.
    Valid URLs (ex. urlParse?)
    Valid characters in: git repo names, file paths
    Verify provided file paths exist
    integers >= 0
    """

    # List of fields, in priority order, which may have a URL, to try and extract a hostname from for max_concurrent_conversions_server_name
    url_fields = ctx.url_fields

    for repo in repos_input:

        ## Ensure each repo has a "max_concurrent_conversions_server_name" attribute, for the purposes of enforcing MAX_CONCURRENT_CONVERSIONS_PER_SERVER; does not need to be a valid address for network connections
        max_concurrent_conversions_server_name = ""

        # Loop through the list
        for url_field in url_fields:

            repo_url = repos_input[repo].get(url_field, "")

            if repo_url:

                try:
                    parsed = urlparse(repo_url)
                    if parsed.hostname:
                        max_concurrent_conversions_server_name = parsed.hostname
                        break

                except Exception as e:
                    log(ctx, f"urlparse failed to parse URL {repo_url}: {e}", "warning")

        # Fallback to code-host-name if provided
        if not max_concurrent_conversions_server_name:
            max_concurrent_conversions_server_name = repos_input[repo].get("code-host-name", "")

        # Last resort: use "unknown"
        if not max_concurrent_conversions_server_name:
            max_concurrent_conversions_server_name = "unknown"
            log(ctx, f"Could not determine server host for repo config: {repo}", "warning")

        # Set the value
        repos_input[repo]["max-concurrent-conversions-server-name"] = max_concurrent_conversions_server_name



    return repos_input


def validate_required_inputs(ctx: Context, repos_input: dict) -> dict:
    """
    If input is marked as required in the list of inputs, then verify every repo has this value
    """



    return repos_input
