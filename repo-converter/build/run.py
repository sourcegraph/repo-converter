#!/usr/bin/env python3
# Python 3.13.2

### TODO:

    # Config file
        # Rewrite as a list of servers
            # Server
                # Name key
                # URL
                # Repo type
                # Username
                # Password
                # Access token
                # SSH key path
                # List of repos
                    # If blank, try and parse the list from the server?

    # SVN

        # Add command execution time to log output, so we can see what's taking longer, the svn log or fetch

        # Try to add the batch size to the svn log command to speed it up

        # SVN commands hanging
            # Add a timeout in run_subprocess() for hanging svn info and svn log commands, if data isn't transferring

        # .gitignore files
            # git svn create-ignore
            # git svn show-ignore
            # https://git-scm.com/docs/git-svn#Documentation/git-svn.txt-emcreate-ignoreem

        # Test layout tags and branches as lists / arrays

        # Run git svn log --xml to store the repo's log on disk, then append to it when there are new revisions, so getting counts of revisions in each repo is slow once, fast many times

    # Git
        # SSH clone
            # Move git SSH clone from outside bash script into this script
            # See if the GitPython module fetches the repo successfully, or has a way to clone multiple branches
                # Fetch (just the default branch)
                # Fetch all branches
                # Clone all branches

            # From the git remote --help
                # Imitate git clone but track only selected branches
                #     mkdir project.git
                #     cd project.git
                #     git init
                #     git remote add -f -t master -m master origin git://example.com/git.git/
                #     git merge origin

    # Other

        # Perms
            # src serve-git and repo-converter both run as root, which is not ideal
            # Need to create a new user on the host, add it to the host's sourcegraph group, get the UID, and configure the runas user for the containers with this UID

        # Debug log the list of servers and repos found in config file at the start of each run?

        # Make repo name a key-value instead of just a key, if repos need non-YAML-safe characters

        # Read environment variables from repos-to-convert.yaml, so the values can be changed without restarting the container

        # Parallelism
            # Config per server
            # Limit per server

        # Add a fetch-interval-seconds config to repos-to-convert.yaml file
            # under the server config
            # convert_svn_repos loop
                # Try and read it
                        # next_fetch_time = repo_key.get(next-fetch-time, None)
                # If it's defined and in the future, skip this run
                    # if next_fetch_time
                        # if next_fetch_time >= time.now()
                            # Log.debug(repo_key next fetch time is: yyyy-mm-dd HH:MM:SS, skipping)
                            # continue
                        # Else
                            # Log.debug(repo_key next fetch time was: yyyy-mm-dd HH:MM:SS, fetching
                # Doing this before forking the process reduces zombies and debug process log noise
            # convert_svn_repo
                # Set the next fetch time to None, so the forking loop doesn't fork again for this repo fetch interval
                    # repo_key[next-fetch-time] = None
                # Check if this repo has a fetch interval defined
                    # fetch_interval_seconds = repo_key.get(fetch-interval-seconds, None)
                    # If yes, calculate and store the next fetch time
                    # If fetch_interval_seconds
                        # repo_key[next-fetch-time] = fetch_interval_seconds + time.now()

        # Add to the process status check and cleanup function to
            # get the last lines of stdout from a running process,
            # instead of just wait with a timeout of 0.1,
            # use communicate() with a timeout and read the stdout from the return value,
            # catch the timeout exception
            # May require tracking process objects in a dict, which would prevent processes from getting auto-cleaned, resulting in higher zombie numbers


    # Add doc strings for each function?
        # https://www.dataquest.io/blog/documenting-in-python-with-docstrings

    # Rewrite in Go?
    # Rewrite in object oriented fashion?

### Notes:

    # psutil requires adding gcc to the Docker image build, which adds 4 minutes to the build time, and doubles the image size
    # It would be handy if there was a workaround without it, but multiprocessing.active_children() doesn't join the intermediate processes that Python forks

    # authors file
        # java -jar /sourcegraph/svn-migration-scripts.jar authors https://svn.apache.org/repos/asf/eagle > authors.txt
        # Kinda useful, surprisingly fast

    # git list all config
        # git -C $local_repo_path config --list

    # Decent example of converting commit messages
    # https://github.com/seantis/git-svn-trac/blob/master/git-svn-trac.py


## Import libraries
# Standard libraries
from datetime import datetime, timedelta                    # https://docs.python.org/3/library/datetime.html
import logging                                              # https://docs.python.org/3/library/logging.html
import multiprocessing                                      # https://docs.python.org/3/library/multiprocessing.html
import os                                                   # https://docs.python.org/3/library/os.html
import random                                               # https://docs.python.org/3/library/random.html
import shutil                                               # https://docs.python.org/3/library/shutil.html
import signal                                               # https://docs.python.org/3/library/signal.html
import subprocess                                           # https://docs.python.org/3/library/subprocess.html
import sys                                                  # https://docs.python.org/3/library/sys.html
import textwrap                                             # https://docs.python.org/3/library/textwrap.html
import time                                                 # https://docs.python.org/3/library/time.html
import traceback                                            # https://docs.python.org/3/library/traceback.html
# Third party libraries
import git                                                  # https://gitpython.readthedocs.io/en/stable/tutorial.html
import psutil                                               # https://pypi.org/project/psutil/
import yaml                                                 # https://pyyaml.org/wiki/PyYAMLDocumentation


# Global variables
environment_variables_dict = {}
git_config_namespace = "repo-converter"
passwords_set = set()
repos_dict = {}
script_name = os.path.basename(__file__)
script_run_number = 0


def register_signal_handler():

    try:

        log(f"Registering signal handler","debug")

        signal.signal(signal.SIGINT, signal_handler)

    except Exception as exception:

        log(f"Registering signal handler failed with exception: {type(exception)}, {exception.args}, {exception}","error")


def signal_handler(incoming_signal, frame):

    log(f"Received signal: {incoming_signal} frame: {frame}","debug")

    signal_name = signal.Signals(incoming_signal).name

    log(f"Handled signal {signal_name}: {incoming_signal} frame: {frame}","debug")


def load_config_from_environment_variables():

    # Try and read the environment variables from the Docker container's environment config
    # Set defaults in case they're not defined

    # DEBUG INFO WARNING ERROR CRITICAL
    environment_variables_dict["LOG_LEVEL"]                         = str(os.environ.get("LOG_LEVEL"                        , "INFO" ))
    environment_variables_dict["REPO_CONVERTER_INTERVAL_SECONDS"]   = int(os.environ.get("REPO_CONVERTER_INTERVAL_SECONDS"  , 3600 ))
    # Path inside the container to find this file, only change to match if the right side of the volume mapping changes
    environment_variables_dict["REPOS_TO_CONVERT"]                  = str(os.environ.get("REPOS_TO_CONVERT"                 , "/sourcegraph/repos-to-convert.yaml" ))
    # Path inside the container to find this directory, only change to match if the right side of the volume mapping changes
    environment_variables_dict["SRC_SERVE_ROOT"]                    = str(os.environ.get("SRC_SERVE_ROOT"                   , "/sourcegraph/src-serve-root" ))

    # Image build info
    environment_variables_dict["BUILD_BRANCH"]                      = str(os.environ.get("BUILD_BRANCH"                     , "" ))
    environment_variables_dict["BUILD_COMMIT"]                      = str(os.environ.get("BUILD_COMMIT"                     , "" ))
    environment_variables_dict["BUILD_DATE"]                        = str(os.environ.get("BUILD_DATE"                       , "" ))
    environment_variables_dict["BUILD_DIRTY"]                       = str(os.environ.get("BUILD_DIRTY"                      , "" ))
    environment_variables_dict["BUILD_TAG"]                         = str(os.environ.get("BUILD_TAG"                        , "" ))


def load_config_from_repos_to_convert_file():
    # Try and load the environment variables from the REPOS_TO_CONVERT file


    # Check if the default config file exists
    # If yes, read configs from it
    # If no, use the environment variables
    pass


def configure_logging():

    logging.basicConfig(
        stream      = sys.stdout,
        datefmt     = "%Y-%m-%d %H:%M:%S",
        encoding    = "utf-8",
        format      = f"%(message)s",
        level       = environment_variables_dict["LOG_LEVEL"]
    )


def log(message, level_name:str = "DEBUG"):

    level_name = str(level_name).upper()

    if level_name in ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]:
        level_int = logging.getLevelName(level_name)
    else:
        level_name = "DEBUG"
        level_int = logging.DEBUG

    date_string = datetime.now().date().isoformat()
    time_string = datetime.now().time().isoformat()
    run_string  = f"run {str(script_run_number)}"
    message     = redact_password(message)
    log_message = f"{date_string}; {time_string}; {run_string}; {level_name}; {str(message)}"

    logging.log(level_int, log_message)


def redact_password(input):

    # Handle different types
    # Return the same type this function was given
    # If input is a dict or list, uses recursion to depth-first-search through the values, with arbitrary depths, keys, and value types

    # If the message is None, or the passwords_set is empty, or none of the passwords in the passwords set are in the input, then just return the input as is
    if (
        isinstance(input, type(None)) or
        isinstance(input, type(bool)) or
        len(passwords_set) == 0 or
        all(password not in input for password in passwords_set)
    ):

        return input

    # If it's type string, just use string's built-in .replace()
    elif isinstance(input, str):

        for password in passwords_set:
            if password in input:
                input_without_password = input.replace(password, "REDACTED-PASSWORD")

    # If it's type int, cast it to a string, then recurse this function again to use string's built-in .replace()
    elif isinstance(input, int):

        # Can't add the redacted message to an int
        input_without_password_string = str(input).replace(password, "")

        # Cast back to an int to return the same type
        input_without_password = int(input_without_password_string)

    # AttributeError: 'list' object has no attribute 'replace'
    # Need to iterate through the items in the list
    elif isinstance(input, list):

        input_without_password = []
        for item in input:

            # Send the list item back through this function to hit any of the non-list types
            input_without_password.append(redact_password(item))

    # If it's a dict, recurse through the dict, until it gets down to primitive types
    elif isinstance(input, dict):

        input_without_password = {}

        for key in input.keys():

            # Check if the password is in the key, and convert it to a string
            key_string = redact_password(str(key))

            # Send the value back through this function to hit any of the non-list types
            input_without_password[key_string] = redact_password(input[key])

    else:

        log(f"redact_password() doesn't handle input of type {type(input)}","error")

        # Set it to None to just break the code instead of leak the password
        input_without_password = None

    return input_without_password


def get_pid_uptime(pid:int = 1):

    pid_uptime = None

    try:

        pid_int                 = int(pid)
        pid_create_time         = psutil.Process(pid_int).create_time()
        pid_start_datetime      = datetime.fromtimestamp(pid_create_time)
        pid_uptime_timedelta    = datetime.now() - pid_start_datetime
        pid_uptime_seconds      = pid_uptime_timedelta.total_seconds()
        pid_uptime              = timedelta(seconds=pid_uptime_seconds)

    except psutil.NoSuchProcess:
        pass

    return pid_uptime


def get_subprocess_run_time(process_dict):

    run_time = None

    if "start_time" in process_dict:

        if "end_time" in process_dict:

            run_time = process_dict["end_time"] - process_dict["start_time"]

        else:

            run_time = datetime.now() - process_dict["start_time"]

    else:

        log(f"process_dict is missing a start_time: {process_dict}", "debug")

    if run_time:

        process_dict["run_time"] = timedelta(seconds=run_time.total_seconds())


def status_update_and_cleanup_zombie_processes():

    # The current approach should return the same list of processes as just ps -ef when a Docker container runs this script as the CMD (pid 1)

    # Get the current process ID, should be 1 in Docker
    os_this_pid = os.getpid()

    # Using a set for built-in deduplication
    process_pids_to_wait_for = set()

    # Get a oneshot snapshot of all processes running this instant
    # Loop through for each processes
    for process in psutil.process_iter():

        # The process may finish in the time between .process_iter() and .parents()
        try:

            # Get all upstream parent PIDs of the process
            # Caught a process doesn't exist exception here, could see if it could be handled
            process_parents_pids = [process_parent.pid for process_parent in process.parents()]

            # If this pid is in the parents, then we know its a child / grandchild / great-grandchild / etc. process of this process
            if os_this_pid in process_parents_pids:

                # Add the process' own PID to the set
                process_pids_to_wait_for.add(process.pid)

                # Loop through the process' parents and add them to the set too
                for process_parents_pid in process_parents_pids:

                    process_pids_to_wait_for.add(process_parents_pid)

        except psutil.NoSuchProcess as exception:

            log(f"Caught an exception when listing parents of processes: {exception}", "debug")

    # Remove this script's PID so it's not waiting on itself
    process_pids_to_wait_for.discard(os_this_pid)

    # Now that we have a set of all child / grandchild / etc PIDs without our own
    # Loop through them and wait for each one
    # If the process is a zombie, then waiting for it:
        # Gets the return value
        # Removes the process from the OS' process table
        # Raises an exception
    for process_pid_to_wait_for in process_pids_to_wait_for:

        process_dict        = {}
        process_to_wait_for = None
        status_message      = ""

        try:

            # Create an instance of a Process object for the PID number
            # Raises psutil.NoSuchProcess if the PID has already finished
            process_to_wait_for = psutil.Process(process_pid_to_wait_for)

            # Get the process attributes from the OS
            process_dict = process_to_wait_for.as_dict()

            # This rarely fires, ex. if cleaning up processes at the beginning of a script execution and the process finished during the interval
            if process_to_wait_for.status() == psutil.STATUS_ZOMBIE:
                status_message = "is a zombie"

            # Wait a short period, and capture the return status
            # Raises psutil.TimeoutExpired if the process is busy executing longer than the wait time
            return_status = process_to_wait_for.wait(0.1)
            status_message = f"finished with return status: {str(return_status)}"

        except psutil.NoSuchProcess as exception:
            status_message = "finished on wait"

        except psutil.TimeoutExpired as exception:
            status_message = "still running"

        except Exception as exception:
            status_message = f"raised an exception while waiting: {type(exception)}, {exception.args}, {exception}"

        if "pid" not in process_dict.keys():
            process_dict["pid"] = process_pid_to_wait_for

        print_process_status(process_dict, status_message)


def git_config_safe_directory():

    cmd_git_safe_directory = ["git", "config", "--system", "--replace-all", "safe.directory", "\"*\""]
    subprocess_run(cmd_git_safe_directory)


def parse_repos_to_convert_file_into_repos_dict():

    # The Python runtime seems to require this to get specified
    global repos_dict

    # Clear the dict for this execution to ignore repos which have been removed from the yaml file
    repos_dict.clear()

    # Parse the repos-to-convert.yaml file
    try:

        # Open the file
        with open(environment_variables_dict["REPOS_TO_CONVERT"], "r") as repos_to_convert_file:

            # This should return a dict
            repos_dict = yaml.safe_load(repos_to_convert_file)

    except FileNotFoundError:

        log(f"repos-to-convert.yaml file not found at {environment_variables_dict['REPOS_TO_CONVERT']}", "error")
        sys.exit(1)

    except (AttributeError, yaml.scanner.ScannerError) as exception:

        log(f"Invalid YAML file format in {environment_variables_dict['REPOS_TO_CONVERT']}, please check the structure matches the format in the README.md. Exception: {type(exception)}, {exception.args}, {exception}", "error")
        sys.exit(2)

    log(f"Parsed {len(repos_dict)} repos from {environment_variables_dict['REPOS_TO_CONVERT']}", "info")

    repos_dict = sanitize_inputs(repos_dict)


def sanitize_inputs(input_value, input_key="", recursed=False):

    # Uses recursion to depth-first-search through the repos_dict dictionary, with arbitrary depths, keys, and value types

    # log(f"sanitize_inputs; starting; type(input_key): {type(input_key)}, input_key: {input_key}, type(input_value): {type(input_value)}, input_value: {input_value}, recursed: {recursed}", "info")

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

        # log(f"sanitize_inputs(): received dict with key: {input_key} and dict: {input_value}", "info")

        output = {}

        for input_value_key in input_value.keys():

            # log(f"sanitize_inputs(): key   type: {type(input_key)}; key: {input_key}", "info")
            # log(f"sanitize_inputs(): value type: {type(input[input_key])}; value: {input[input_key]}", "info")

            # Convert the key to a string
            output_key = str(input_value_key)

            # Recurse back into this function to handle the values of this dict
            output[output_key] = sanitize_inputs(input_value[input_value_key], input_value_key, True)

    # If this function was called with a list
    elif isinstance(input_value, list):

        # log(f"sanitize_inputs(): received list with key: {input_key} and list: {input_value}", "info")

        output = []

        for input_list_item in input_value:

            # log(f"sanitize_inputs(): type(input_list_item): {type(input_list_item)}; input_list_item: {input_list_item}", "info")

            # Recurse back into this function to handle the values of this list
            output.append(sanitize_inputs(input_list_item, input_key, True))

    else:

        # If the key is in the input_value_types_dict, then validate the value type
        if input_key in input_value_types_dict.keys():

            # If the value's type is in the tuple, then just copy it as is
            if type(input_value) in input_value_types_dict[input_key]:

                output = input_value

            # Type doesn't match
            else:

                # Construct the warning message
                type_warning_message = f"Parsing {environment_variables_dict['REPOS_TO_CONVERT']} found incorrect variable type for "

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
                passwords_set.add(input_value)

        else:

            log(f"No type check for {input_key}: {input_value} variable in {environment_variables_dict['REPOS_TO_CONVERT']}", "warning")
            output = input_value

    # log(f"sanitize_inputs; ending; type(output): {type(output)}, output: {output}", "info")
    return output


def deduplicate_git_config_file(git_config_file_path):

    log(f"deduplicate_git_config_file; git_config_file_path: {git_config_file_path}", "debug")

    # Use a set to store lines already seen
    # as it deduplicates lines automatically
    # however, don't write the set back to the file,
    # because it's unordered
    lines_seen = set()

    # Open the config file, in read/write mode, so we can overwrite its contents
    with open(git_config_file_path, "r+") as config_file:

        # Read the whole file's contents into memory
        config_file_data = config_file.readlines()

        log(f"deduplicate_git_config_file; git_config_file lines before: {len(config_file_data)}", "debug")

        # Move the file pointer back to the beginning of the file to start overwriting from there
        config_file.seek(0)

        # Iterate through the lines in their existing order
        for line in config_file_data:

            # If we haven't seen this line before / isn't a duplicate
            if line not in lines_seen:

                # Write it back to the config file, with a newline
                config_file.write(line + "\n")

                # Add it to the set of lines we've seen
                lines_seen.add(line)

        # Delete the rest of the file's contents
        config_file.truncate()

        log(f"deduplicate_git_config_file; git_config_file lines after: {len(lines_seen)}", "debug")


def clone_svn_repos():

    # Loop through the repos_dict, find the type: SVN repos, then fork off a process to clone them
    for repo_key in repos_dict.keys():

        repo_type = repos_dict[repo_key].get("type","").lower()

        if repo_type in ("svn", "subversion"):

            multiprocessing.Process(target=clone_svn_repo, name=f"clone_svn_repo_{repo_key}", args=(repo_key,)).start()


def clone_svn_repo(repo_key):

    # Get config parameters read from repos-to-clone.yaml, and set defaults if they're not provided
    git_repo_name               = repo_key
    authors_file_path           = repos_dict[repo_key].get("authors-file-path"    , None    )
    authors_prog_path           = repos_dict[repo_key].get("authors-prog-path"    , None    )
    bare_clone                  = repos_dict[repo_key].get("bare-clone"           , True    )
    branches                    = repos_dict[repo_key].get("branches"             , None    )
    code_host_name              = repos_dict[repo_key].get("code-host-name"       , None    )
    fetch_batch_size            = repos_dict[repo_key].get("fetch-batch-size"     , 100     )
    git_default_branch          = repos_dict[repo_key].get("git-default-branch"   , "trunk" )
    git_ignore_file_path        = repos_dict[repo_key].get("git-ignore-file-path" , None    )
    git_org_name                = repos_dict[repo_key].get("git-org-name"         , None    )
    layout                      = repos_dict[repo_key].get("layout"               , None    )
    password                    = repos_dict[repo_key].get("password"             , None    )
    svn_remote_repo_code_root   = repos_dict[repo_key].get("svn-repo-code-root"   , None    )
    tags                        = repos_dict[repo_key].get("tags"                 , None    )
    trunk                       = repos_dict[repo_key].get("trunk"                , None    )
    username                    = repos_dict[repo_key].get("username"             , None    )

    ## Parse config parameters into command args
    # TODO: Interpret code_host_name, git_org_name, and git_repo_name if not given
        # ex. https://svn.apache.org/repos/asf/parquet/site
        # code_host_name            = svn.apache.org    # can get by removing url scheme, if any, till the first /
        # arbitrary path on server  = repos             # optional, can either be a directory, or may actually be the repo
        # git_org_name              = asf
        # git_repo_name             = parquet
        # git repo root             = site              # arbitrary path inside the repo where contributors decided to start storing /trunk /branches /tags and other files to be included in the repo
    local_repo_path = f"{environment_variables_dict['SRC_SERVE_ROOT']}/{code_host_name}/{git_org_name}/{git_repo_name}"
    git_config_file_path = f"{local_repo_path}/.git/config"

    ## Define common command args
    arg_batch_end_revision          =           [ f"{git_config_namespace}.batch-end-revision"  ]
    arg_git                         =           [ "git", "-C", local_repo_path                  ]
    arg_git_cfg                     = arg_git + [ "config"                                      ]
    arg_git_svn                     = arg_git + [ "svn"                                         ]
    arg_svn_echo_password           = None
    arg_svn_non_interactive         =           [ "--non-interactive"                           ] # Do not prompt, just fail if the command doesn't work, only used for direct `svn` command
    arg_svn_password                =           [ "--password", password                        ] # Only used for direct `svn` commands
    arg_svn_remote_repo_code_root   =           [ svn_remote_repo_code_root                     ]
    arg_svn_username                =           [ "--username", username                        ]

    ## Define commands
    # One offs in the new array
    # Reused one in their own arrays above, even if they're single element arrays
    cmd_git_authors_file            = arg_git_cfg + [ "svn.authorsfile", authors_file_path                      ]
    cmd_git_authors_prog            = arg_git_cfg + [ "svn.authorsProg", authors_prog_path                      ]
    cmd_git_bare_clone              = arg_git_cfg + [ "core.bare", "true"                                       ]
    cmd_git_default_branch          = arg_git     + [ "symbolic-ref", "HEAD", f"refs/heads/{git_default_branch}"]
    cmd_git_garbage_collection      = arg_git     + [ "gc"                                                      ]
    cmd_git_get_batch_end_revision  = arg_git_cfg + [ "--get"                                                   ] + arg_batch_end_revision
    cmd_git_get_svn_url             = arg_git_cfg + [ "--get", "svn-remote.svn.url"                             ]
    cmd_git_set_batch_end_revision  = arg_git_cfg + [ "--replace-all"                                           ] + arg_batch_end_revision
    cmd_git_svn_fetch               = arg_git_svn + [ "fetch"                                                   ]
    cmd_git_svn_init                = arg_git_svn + [ "init"                                                    ] + arg_svn_remote_repo_code_root
    cmd_svn_info                    =               [ "svn", "info"                                             ] + arg_svn_non_interactive + arg_svn_remote_repo_code_root
    cmd_svn_log                     =               [ "svn", "log", "--xml", "--with-no-revprops"               ] + arg_svn_non_interactive + arg_svn_remote_repo_code_root

    ## Modify commands based on config parameters
    if username:
        cmd_svn_info            += arg_svn_username
        cmd_svn_log             += arg_svn_username
        cmd_git_svn_init        += arg_svn_username
        cmd_git_svn_fetch       += arg_svn_username

    if password:
        arg_svn_echo_password    = True
        cmd_svn_info            += arg_svn_password
        cmd_svn_log             += arg_svn_password

    # States
        # Create:
            # State:
                # The directory doesn't already exist
                # The repo      doesn't already exist
            # How did we get here:
                # First time - Create new path / repo / fetch job
                # First run of the script
                # New repo was added to the repos-to-convert.yaml file
                # Repo was deleted from disk
            # Approach:
                # Harder to test for the negative, so assume we're in the Create state, unless we find we're in the Running or Update states
    repo_state = "create"
        # Running:
            # State:
                # An svn fetch process is still running
            # How did we get here:
                # Fetch process is still running from a previous run of the script
            # Approach:
                # Check first if the process is running, then continue this outer loop
        # Update:
            # State:
                # Repo already exists, with a valid configuration
            # How did we get here:
                # A fetch job was previously run, but is not currently running
            # Approach:
                # Check if we're in the update state, then set repo_state = "update"
    # repo_state = "update"


    ## Check if we're in the Running state

    # Check if a fetch or log process is currently running for this repo
    # Running this inside of this function instead of breaking it out into its own function
    # due to the number of parameters which would have to be passed
    max_tries = 2
    for i in range(1, max_tries + 1):
        try:

            # Get running processes, both as a list and string
            ps_command = ["ps", "--no-headers", "-e", "--format", "pid,args"]
            running_processes = subprocess_run(ps_command)["output"]
            running_processes_string        = " ".join(running_processes)

            # Define the list of strings we're looking for in the running processes' commands
            cmd_git_svn_fetch_string            = " ".join(cmd_git_svn_fetch)
            cmd_git_garbage_collection_string   = " ".join(cmd_git_garbage_collection)
            cmd_svn_log_string                  = " ".join(cmd_svn_log)
            process_name                        = f"clone_svn_repo_{repo_key}"
            log_failure_message                 = ""

            # In priority order
            concurrency_error_strings_and_messages = [
                (process_name,                      "Previous process still"                ),
                (cmd_git_svn_fetch_string,          "Previous fetching process still"       ),
                (cmd_svn_log_string,                "Previous svn log process still"        ),
                (cmd_git_garbage_collection_string, "Git garbage collection process still"  ),
                (local_repo_path,                   "Local repo path in process"            ), # Problem: if one repo's name is a substring of another repo's name
            ]

            # Loop through the list of strings we're looking for, to check the running processes for each of them
            for concurrency_error_string_and_message in concurrency_error_strings_and_messages:

                # If this string we're looking for is found
                if concurrency_error_string_and_message[0] in running_processes_string:

                    # Find which process it's in
                    for i in range(len(running_processes)):

                        running_process = running_processes[i]
                        pid, args = running_process.lstrip().split(" ", 1)

                        # If it's this process, and this process hasn't already matched one of the previous concurrency errors
                        if (
                            concurrency_error_string_and_message[0] in args and
                            pid not in log_failure_message
                        ):

                            # Add its message to the string
                            log_failure_message += f"{concurrency_error_string_and_message[1]} running in pid {pid}; "

                            # Calculate its running time
                            # Quite often, processes will complete when get_pid_uptime() checks them; if this is the case, then try this check again
                            pid_uptime = get_pid_uptime(pid)
                            if pid_uptime:

                                log_failure_message += f"running for {pid_uptime}; "

                            else:

                                # Check the process again to see if it's still running
                                log(f"{repo_key}; pid {pid} with command {args} completed while checking for concurrency collisions, will try checking again", "debug")
                                i -= 1

                            log_failure_message += f"with command: {args}; "

            if log_failure_message:

                log_failure_message = f"{repo_key}; {log_failure_message}skipping"
                log(log_failure_message, "info")
                return

            else:

                # If we got here, then there isn't another process running, and no Exceptions, so we can break out of the for loop
                break

        except Exception as exception:

            log(f"{repo_key}; Failed check {i} of {max_tries} if fetching process is already running. Exception: {type(exception)}, {exception.args}, {exception}", "warning")

            stack = traceback.extract_stack()
            (filename, line, procname, text) = stack[-1]

            log(f"filename, line, procname, text: {filename, line, procname, text}", "debug")

            # Raising this exception kills the multiprocessing process, so it doesn't try to run this cycle
            #raise exception


    ## Check if we're in the Update state
    # Check if the git repo already exists and has the correct settings in the config file
    try:

        svn_remote_url = subprocess_run(cmd_git_get_svn_url, quiet=True)["output"][0]

        if svn_remote_url in svn_remote_repo_code_root:

            repo_state = "update"

    except Exception as exception:
        # Get an error when trying to git config --get svn-remote.svn.url, when the directory doesn't exist on disk
        # WARNING; karaf; failed to check git config --get svn-remote.svn.url. Exception: <class 'TypeError'>, ("'NoneType' object is not subscriptable",), 'NoneType' object is not subscriptable
        log(f"{repo_key}; failed to check git config --get svn-remote.svn.url. Exception: {type(exception)}, {exception.args}, {exception}", "warning")


    ## Run commands
    # Run the svn info command to test logging in to the SVN server, for network connectivity and credentials
    # Capture the output so we know the max revision in this repo's history
    svn_info = subprocess_run(cmd_svn_info, password, arg_svn_echo_password)
    svn_info_output_string = " ".join(svn_info["output"])

    if svn_info["returncode"] != 0:

        # The clone_svn_repo function runs in its own process, get this process' start time
        # Check for current time < start time + REPO_CONVERTER_INTERVAL_SECONDS, to ensure that this retry is not extending beyond the interval
        process_create_time = psutil.Process(os.getpid()).create_time()

        # Let it retry up top 80% of the time remaining until the next REPO_CONVERTER_INTERVAL_SECONDS, so this process doesn't overrun the current interval
        retry_time_limit = process_create_time + int(environment_variables_dict["REPO_CONVERTER_INTERVAL_SECONDS"] * 0.8)

        # Set a maximum retry delay of one third of REPO_CONVERTER_INTERVAL_SECONDS, so it can retry 2-3 times, or 60 seconds, whichever is shorter
        retry_delay_range = min(int(environment_variables_dict["REPO_CONVERTER_INTERVAL_SECONDS"] / 3), 60)

        # Set a maximum number of retries per script run
        retry_attempts_max  = 3
        retries_attempted   = 0

        svn_connection_failure_message_to_check_for = "Unable to connect to a repository at"

        while (
            svn_connection_failure_message_to_check_for in svn_info_output_string and
            time.time() < retry_time_limit and
            retries_attempted < retry_attempts_max
        ):

            retries_attempted += 1
            retry_delay_seconds = random.randrange(1, retry_delay_range)

            log(f"{repo_key}; Failed to connect to repo remote, retrying {retries_attempted} of max {retry_attempts_max} times, with a semi-random delay of {retry_delay_seconds} seconds", "warning")

            time.sleep(retry_delay_seconds)

            svn_info = subprocess_run(cmd_svn_info, password, arg_svn_echo_password)
            svn_info_output_string = " ".join(svn_info["output"])

        if svn_info["returncode"] != 0:

            log_failure_message = ""

            if retries_attempted == retry_attempts_max:
                log_failure_message = f"hit retry count limit {retry_attempts_max} for this run"

            elif not time.time() < retry_time_limit:
                log_failure_message = f"hit retry time limit for this run"

            log(f"{repo_key}; Failed to connect to repo remote, {log_failure_message}, skipping", "error")
            return

        else:

            log(f"{repo_key}; Successfully connected to repo remote after {retries_attempted} retries", "warning")

    # Get last changed revision for this repo
    last_changed_rev = svn_info_output_string.split("Last Changed Rev: ")[1].split(" ")[0]

    # Check if the previous batch end revision is the same as the last changed rev from svn info
    # If yes, we're up to date, return to the next repo, instead of forking the git svn process to do the same check
    if repo_state == "update":

        #  TypeError: 'NoneType' object is not subscriptable
        try:
            previous_batch_end_revision = subprocess_run(cmd_git_get_batch_end_revision)["output"][0]
        except Exception as exception:
            previous_batch_end_revision = "1"

        if previous_batch_end_revision == last_changed_rev:

            log(f"{repo_key}; up to date; skipping; local rev {previous_batch_end_revision}, remote rev {last_changed_rev}", "info")

            # Run git garbage collection and cleanup branches, even if repo is already up to date
            subprocess_run(cmd_git_garbage_collection)
            cleanup_branches_and_tags(local_repo_path, cmd_git_default_branch, git_default_branch)

            return

        else:

            # Write and run the command
            cmd_svn_log_remaining_revs = cmd_svn_log + ["--revision", f"{previous_batch_end_revision}:HEAD"]
            svn_log = subprocess_run(cmd_svn_log_remaining_revs, password, arg_svn_echo_password)

            # Parse the output to get the number of remaining revisions
            svn_log_output_string = " ".join(svn_log["output"])
            remaining_revs_count = svn_log_output_string.count("revision=")

            # Log the results
            log(f"{repo_key}; out of date; local rev {previous_batch_end_revision}, remote rev {last_changed_rev}, {remaining_revs_count} revs remaining to catch up, fetching next batch of {min(remaining_revs_count,fetch_batch_size)} revisions; svn log command run time {svn_log['run_time']}", "info")


    if repo_state == "create":

        log(f"{repo_key}; didn't find a local clone, creating one", "info")

        # Create the repo path if it doesn't exist
        if not os.path.exists(local_repo_path):
            os.makedirs(local_repo_path)

        if layout:
            cmd_git_svn_init   += ["--stdlayout"]

            # Warn the user if they provided an invalid value for the layout, only standard is supported
            if "standard" not in layout and "std" not in layout:
                log(f"{repo_key}; Layout shortcut provided with incorrect value {layout}, only standard is supported for the shortcut, continuing assuming standard, otherwise provide --trunk, --tags, and --branches", "warning")

        # There can only be one trunk
        if trunk:
            cmd_git_svn_init            += ["--trunk", trunk]

        # Tags and branches can either be single strings or lists of strings
        if tags:
            if isinstance(tags, str):
                cmd_git_svn_init        += ["--tags", tags]
            if isinstance(tags, list):
                for tag in tags:
                    cmd_git_svn_init    += ["--tags", tag]
        if branches:
            if isinstance(branches, str):
                cmd_git_svn_init        += ["--branches", branches]
            if isinstance(branches, list):
                for branch in branches:
                    cmd_git_svn_init    += ["--branches", branch]

        # Initialize the repo
        subprocess_run(cmd_git_svn_init, password, arg_svn_echo_password)

        # Configure the bare clone
        if bare_clone:
            subprocess_run(cmd_git_bare_clone)

        # Initialize this config with a 0 value
        cmd_git_set_batch_end_revision.append(str(0))
        subprocess_run(cmd_git_set_batch_end_revision)


    ## Back to steps we do for both Create and Update states, so users can update the below parameters without having to restart the clone from scratch
    # TODO: Check if these configs are already set the same before trying to set them

    # Set the default branch local to this repo, after init
    subprocess_run(cmd_git_default_branch)

    # Configure the authors file, if provided
    if authors_file_path:
        if os.path.exists(authors_file_path):
            subprocess_run(cmd_git_authors_file)
        else:
            log(f"{repo_key}; authors file not found at {authors_file_path}, skipping configuring it", "warning")

    # Configure the authors program, if provided
    if authors_prog_path:
        if os.path.exists(authors_prog_path):
            subprocess_run(cmd_git_authors_prog)
        else:
            log(f"{repo_key}; authors prog not found at {authors_prog_path}, skipping configuring it", "warning")

    # Configure the .gitignore file, if provided
    if git_ignore_file_path:
        if os.path.exists(git_ignore_file_path):
            shutil.copy2(git_ignore_file_path, local_repo_path)
        else:
            log(f"{repo_key}; .gitignore file not found at {git_ignore_file_path}, skipping configuring it", "warning")

    # Batch processing
    batch_start_revision    = None
    batch_end_revision      = None

    try:

        # Get the revision number to start with
        if repo_state == "update":

            # Try to retrieve repo-converter.batch-end-revision from git config
            # previous_batch_end_revision = git config --get repo-converter.batch-end-revision
            # Need to fail gracefully
            previous_batch_end_revision = subprocess_run(cmd_git_get_batch_end_revision)["output"]

            if previous_batch_end_revision:

                batch_start_revision = int(" ".join(previous_batch_end_revision)) + 1

        if repo_state == "create" or batch_start_revision == None:

            # If this is a new repo, get the first changed revision number for this repo from the svn server log
            cmd_svn_log_batch_start_revision = cmd_svn_log + ["--limit", "1", "--revision", "1:HEAD"]
            svn_log_batch_start_revision = subprocess_run(cmd_svn_log_batch_start_revision, password, arg_svn_echo_password)["output"]
            batch_start_revision = int(" ".join(svn_log_batch_start_revision).split("revision=\"")[1].split("\"")[0])

        # Get the revision number to end with
        if batch_start_revision:

            # Get the batch size'th revision number for the rev to end this batch range
            cmd_svn_log_batch_end_revision = cmd_svn_log + ["--limit", str(fetch_batch_size), "--revision", f"{batch_start_revision}:HEAD"]
            cmd_svn_log_batch_end_revision_output = subprocess_run(cmd_svn_log_batch_end_revision, password, arg_svn_echo_password)["output"]

            try:

                # While we're at it, update the batch starting rev to the first real rev number after the previous end rev +1
                batch_start_revision = int(" ".join(cmd_svn_log_batch_end_revision_output).split("revision=\"")[1].split("\"")[0])

                # Reverse the output so we can get the last revision number
                cmd_svn_log_batch_end_revision_output.reverse()
                batch_end_revision = int(" ".join(cmd_svn_log_batch_end_revision_output).split("revision=\"")[1].split("\"")[0])

            except IndexError as exception:
                log(f"{repo_key}; IndexError when getting batch start or end revisions for batch size {fetch_batch_size}, skipping this run to retry next run", "warning")
                return

                # log(f"{repo_key}; IndexError when getting batch start or end revisions for batch size {fetch_batch_size}; running the fetch without the batch size limit; exception: {type(exception)}, {exception.args}, {exception}", "warning")
                #  <class 'IndexError'>, ('list index out of range',), list index out of range
                # Need to handle the issue where revisions seem to be out of order on the server

        # If we were successful getting both starting and ending revision numbers
        if batch_start_revision and batch_end_revision:

            # Use them
            cmd_git_svn_fetch += ["--revision", f"{batch_start_revision}:{batch_end_revision}"]

    except Exception as exception:

        # Log a warning if this fails, and run the fetch without the --revision arg
        # log(f"{repo_key}; failed to get batch start or end revision for batch size {fetch_batch_size}; running the fetch without the batch size limit; exception: {type(exception)}, {exception.args}, {exception}", "warning")

        log(f"{repo_key}; failed to get batch start or end revision for batch size {fetch_batch_size}; skipping this run to retry next run; exception: {type(exception)}, {exception.args}, {exception}", "warning")
        return

    # Delete duplicate lines from the git config file, before the fetch
    # hoping that it increases our chances of a successful fetch
    deduplicate_git_config_file(git_config_file_path)

    # Start the fetch
    cmd_git_svn_fetch_string_may_have_batch_range = " ".join(cmd_git_svn_fetch)
    log(f"{repo_key}; fetching with {cmd_git_svn_fetch_string_may_have_batch_range}", "info")
    git_svn_fetch_result = subprocess_run(cmd_git_svn_fetch, password, password)

    # If the fetch succeed, and if we have a batch_end_revision
    if git_svn_fetch_result["returncode"] == 0 and batch_end_revision:

        # Store the ending revision number
        cmd_git_set_batch_end_revision.append(str(batch_end_revision))
        subprocess_run(cmd_git_set_batch_end_revision)

        log(f"{repo_key}; git fetch complete; run time {git_svn_fetch_result['run_time']}", "info")

    else:

        log(f"{repo_key}; git fetch failed; run time {git_svn_fetch_result['run_time']}", "error")

    # Run Git garbage collection before handing off to cleanup branches and tags
    subprocess_run(cmd_git_garbage_collection)

    cleanup_branches_and_tags(local_repo_path, cmd_git_default_branch, git_default_branch)


def clone_tfs_repos():
    log("Cloning TFS repos function not implemented yet", "warning")

    # # Declare an empty dict for TFS repos to extract them from the repos_dict
    # tfs_repos_dict = {}

    # # Loop through the repos_dict, find the type: tfs repos, then add them to the dict of TFS repos
    # for repo_key in repos_dict.keys():

    #     repo_type = repos_dict[repo_key].get('type','').lower()

    #     if repo_type == 'tfs' or repo_type == 'tfvc':

    #         tfs_repos_dict[repo_key] = repos_dict[repo_key]


    # log(f"Cloning TFS repos: {str(tfs_repos_dict)}", "info")


def clone_git_repos():
    log("Cloning Git repos function not implemented yet", "warning")


def cleanup_branches_and_tags(local_repo_path, cmd_git_default_branch, git_default_branch):

    # Git svn and git tfs both create converted branches as remote branches, so the Sourcegraph clone doesn't show them to users
    # Need to convert the remote branches to local branches, so Sourcegraph users can see them

    packed_refs_file_path       = f"{local_repo_path}/.git/packed-refs"

    local_branch_prefix         = "refs/heads/"
    local_tag_prefix            = "refs/tags/"
    remote_branch_prefix        = "refs/remotes/origin/"
    remote_tag_prefix           = "refs/remotes/origin/tags/"

    remote_branch_exclusions    = [
        "@",
    ]
    remote_tag_exclusions       = [
        "@",
    ]

    # Read the file content as lines into a list
    with open(packed_refs_file_path, "r") as packed_refs_file:
        input_lines = packed_refs_file.read().splitlines()

    output_list_of_strings_and_line_number_tuples = []
    output_list_of_reversed_tuples = []

    for i in range(len(input_lines)):

        try :

            hash, path = input_lines[i].split(" ")

        except ValueError:

            output_list_of_strings_and_line_number_tuples.append([str(input_lines[i]), i])

            continue

        except Exception as exception:

            log(f"Exception while cleaning branches and tags: {exception}", "error")
            continue

        # If the path is a local tag, then delete it
        if path.startswith(local_tag_prefix):
            continue

        # If the path is a local branch, then delete it
        elif path.startswith(local_branch_prefix):
            continue

        # If the path is the git-svn's default remote branch, then keep it as is, and add a new default local branch
        elif path == "refs/remotes/git-svn":

            output_list_of_reversed_tuples.append(tuple([path,hash]))
            output_list_of_reversed_tuples.append(tuple([f"{local_branch_prefix}{git_default_branch}",hash]))

        # If the path is the default branch, then delete it, it'll get recreated later
        elif path == f"{local_branch_prefix}{git_default_branch}":
            continue

        # If the path is the incorrectly formatted default branch, then delete it
        elif path == f"{local_branch_prefix}/{git_default_branch}":
            continue

        # If the path is a remote tag, then copy it to a local path
        elif path.startswith(remote_tag_prefix):

            output_list_of_reversed_tuples.append(tuple([path,hash]))

            # Filter out the junk
            # If none of the exclusions are in this path, then use it
            filter=(exclusion in path for exclusion in remote_tag_exclusions)
            if not any(filter):

                new_path = path.replace(remote_tag_prefix, local_tag_prefix)
                output_list_of_reversed_tuples.append(tuple([new_path,hash]))

        # If the path is a remote branch, then copy it to a local path
        elif path.startswith(remote_branch_prefix):

            output_list_of_reversed_tuples.append(tuple([path,hash]))

            # Filter out the junk
            # If none of the exclusions are in this path, then use it
            filter=(exclusion in path for exclusion in remote_branch_exclusions)
            if not any(filter):

                new_path = path.replace(remote_branch_prefix, local_branch_prefix)
                output_list_of_reversed_tuples.append(tuple([new_path,hash]))

        else:

            log(f"Error while cleaning branches and tags, not sure how to handle line {input_lines[i]} in {packed_refs_file_path}", "error")
            output_list_of_strings_and_line_number_tuples.append([str(input_lines[i]), i])

    # Sort by the path in the tuple
    output_list_of_reversed_tuples.sort()

    # Reverse the tuple pairs back to "hash path"
    # Convert the tuples back to strings
    output_list_of_strings = [f"{hash} {path}" for path, hash in output_list_of_reversed_tuples]

    # Re-insert the strings that failed to split, back in their original line number
    for string, line_number in output_list_of_strings_and_line_number_tuples:
        output_list_of_strings.insert(line_number, string)

    # Write the content back to the file
    with open(packed_refs_file_path, "w") as packed_refs_file:
        for line in output_list_of_strings:
            packed_refs_file.write(f"{line}\n")

    # Reset the default branch
    subprocess_run(cmd_git_default_branch)


def subprocess_run(args, password=None, echo_password=None, quiet=False):

    return_dict                         = {}
    return_dict["returncode"]           = 1
    return_dict["output"]               = None
    return_dict["start_time"]           = datetime.now()
    truncated_subprocess_output_to_log  = None
    log_level                           = "debug"

    try:

        # Create the process object and start it
        subprocess_to_run = psutil.Popen(
            args    = args,
            stdin   = subprocess.PIPE,
            stdout  = subprocess.PIPE,
            stderr  = subprocess.STDOUT,
            text    = True,
        )

        # Get the process attributes from the OS
        process_dict = subprocess_to_run.as_dict()

        # Log a starting message
        status_message = "started"
        print_process_status(process_dict, status_message)

        # If password is provided to this function, feed it into the subprocess' stdin pipe
        # communicate() also waits for the process to finish
        if echo_password:
            subprocess_output = subprocess_to_run.communicate(password)

        else:
            subprocess_output = subprocess_to_run.communicate()

        # Set the output to return
        subprocess_output = subprocess_output[0].splitlines()
        return_dict["output"] = subprocess_output

        # Set the output to log
        truncated_subprocess_output_to_log = truncate_subprocess_output(subprocess_output)

        # If the process exited successfully
        if subprocess_to_run.returncode == 0:

            status_message = "succeeded"

            return_dict["returncode"] = 0

        else:

            status_message = "failed"

            if not quiet:
                log_level = "error"

    # Catching the CalledProcessError exception,
    # only to catch in case that the subprocess' proc _itself_ raised an exception
    # not necessarily any below processes the subprocess created
    except subprocess.CalledProcessError as exception:

            status_message = f"raised an exception: {type(exception)}, {exception.args}, {exception}"

            if not quiet:
                log_level = "error"

    # If the command fails
    if subprocess_to_run.returncode != 0:

        # There's a high chance it was caused by one of the lock files
        # If check_lock_files successfully cleared a lock file,
        if check_lock_files(args, process_dict):

            # Change the log_level to debug so the failed process doesn't log an error in print_process_status()
            log_level = "debug"

    print_process_status(process_dict, status_message, str(truncated_subprocess_output_to_log), log_level)

    return_dict["end_time"] = datetime.now()
    get_subprocess_run_time(return_dict)

    return return_dict


def truncate_subprocess_output(subprocess_output):

    # If the output is longer than max_output_total_characters, it's probably just a list of all files converted, so truncate it
    max_output_total_characters = 1000
    max_output_line_characters  = 200
    max_output_lines            = 10

    if len(str(subprocess_output)) > max_output_total_characters:

        # If the output list is longer than max_output_lines lines, truncate it
        subprocess_output = subprocess_output[-max_output_lines:]
        subprocess_output.append(f"...LOG OUTPUT TRUNCATED TO {max_output_lines} LINES")

        # Truncate really long lines
        for i in range(len(subprocess_output)):

            if len(subprocess_output[i]) > max_output_line_characters:
                subprocess_output[i] = textwrap.shorten(subprocess_output[i], width=max_output_line_characters, placeholder=f"...LOG LINE TRUNCATED TO {max_output_line_characters} CHARACTERS")

    return subprocess_output


def check_lock_files(args, process_dict):

    return_value                = False
    repo_path                   = args[2] # [ "git", "-C", local_repo_path, "gc" ]
    list_of_process_and_lock_file_path_tuples = [
        ("Git garbage collection"       , ".git/gc.pid"                                     ), # fatal: gc is already running on machine '75c377aedbaf' pid 3700 (use --force if not)
        ("svn config"                   , ".git/svn/.metadata.lock"                         ), # error: could not lock config file .git/svn/.metadata: File exists config svn-remote.svn.branches-maxRev 125551: command returned error: 255
        ("git svn fetch git-svn"        , ".git/svn/refs/remotes/git-svn/index.lock"        ), # fatal: Unable to create '/sourcegraph/src-serve-root/svn.apache.org/asf/xmlbeans/.git/svn/refs/remotes/git-svn/index.lock': File exists.
        ("git svn fetch origin trunk"   , ".git/svn/refs/remotes/origin/trunk/index.lock"   ), # fatal: Unable to create '/sourcegraph/src-serve-root/svn.apache.org/asf/xmlbeans/.git/svn/refs/remotes/origin/trunk/index.lock': File exists
    ]

    # TypeError: can only join an iterable
    try:
        process_command = " ".join(process_dict["cmdline"])
    except TypeError as exception:
        process_command = process_dict["cmdline"]

    pid             = process_dict["pid"]

    for lock_file in list_of_process_and_lock_file_path_tuples:

        process = lock_file[0]
        lock_file_path = f"{repo_path}/{lock_file[1]}"

        if os.path.exists(lock_file_path):

            try:

                lock_file_content = ""

                try:

                    with open(lock_file_path, "r") as lock_file_object:
                        lock_file_content = lock_file_object.read()

                except UnicodeDecodeError as exception:
                    lock_file_content = exception

                log(f"pid {pid} failed; {process} failed to start due to finding a lock file in the repo at {lock_file_path}, but no other process is running with {process_command}; deleting the lock file so it'll try again on the next run; lock file content: {lock_file_content}", "warning")

                cmd_rm_lock_file = ["rm", "-f", lock_file_path]
                subprocess_run(cmd_rm_lock_file)

                return_value = True

            except subprocess.CalledProcessError as exception:
                log(f"Failed to rm -f lock file at {lock_file_path} with exception: {type(exception)}, {exception.args}, {exception}", "error")

    return return_value


def print_process_status(process_dict = {}, status_message = "", std_out = "", log_level = "debug"):

    log_message = ""

    process_attributes_to_log = [
        "ppid",
        "name",
        "cmdline",
        "status",
        "num_fds",
        "cpu_times",
        "memory_percent",
        "connections_count",
        "connections",
        "open_files",
        "start_time",
        "end_time",
        "run_time",
    ]

    pid = process_dict['pid']

    try:

        # Formulate the log message
        log_message += f"pid {pid}; "

        if status_message == "started":

            log_message += f"started;   "

        else:

            log_message += f"{status_message}; "

            # Calculate its running time
            pid_uptime = get_pid_uptime(pid)

            if pid_uptime:
                log_message += f"running for {pid_uptime}; "

        # Pick the interesting bits out of the connections list
        # connections is usually in the dict, as a zero-length list of "pconn"-type objects, (named tuples of tuples)
        if "connections" in process_dict.keys():

            connections = process_dict["connections"]

            if isinstance(connections, list):

                process_dict["connections_count"] = len(process_dict["connections"])

                connections_string = ""

                for connection in connections:

                    # raddr=addr(ip='93.186.135.91', port=80), status='ESTABLISHED'),
                    connections_string += ":".join(map(str,connection.raddr))
                    connections_string += ":"
                    connections_string += connection.status
                    connections_string += ", "

                process_dict["connections"] = connections_string[:-2]

        process_dict_to_log = {key: process_dict[key] for key in process_attributes_to_log if key in process_dict}
        log_message += f"process_dict: {process_dict_to_log}; "

        if std_out:
            log_message += f"std_out: {std_out}; "

    except psutil.NoSuchProcess:
        log_message = f"pid {pid}; finished on status check"

    log(log_message, log_level)


def main():

    global script_run_number
    start_datetime = datetime.fromtimestamp(psutil.Process().create_time()).strftime("%Y-%m-%d %H:%M:%S")
    multiprocessing_start_method = multiprocessing.get_start_method()

    load_config_from_environment_variables()
    configure_logging()
    register_signal_handler()

    while True:

        script_run_number += 1

        load_config_from_repos_to_convert_file()

        # If logging level read from the repos_to_convert_file != current logging level
        load_config_from_environment_variables()
        configure_logging()

        # Calculate uptime
        uptime = get_pid_uptime()

        # Try to get the run as user
        run_as_user = "unknown"
        try:
            run_as_user = os.getlogin()
        except Exception:
            log(f"Failed to get run as user via os.getlogin()", "debug")

        log(f"Starting {script_name} run {script_run_number} with args: {str(environment_variables_dict)}; container ID: {os.uname().nodename}; uptime: {uptime}; running since {start_datetime}; using multiprocessing start method: {multiprocessing_start_method}; running as user: {run_as_user}", "info")

        status_update_and_cleanup_zombie_processes()
        git_config_safe_directory()
        parse_repos_to_convert_file_into_repos_dict()
        clone_svn_repos()
        # clone_tfs_repos()
        # clone_git_repos()
        status_update_and_cleanup_zombie_processes()

        # Calculate uptime
        uptime = get_pid_uptime()

        log(f"Finishing {script_name} run {script_run_number} with args: {str(environment_variables_dict)}; container ID: {os.uname().nodename}; uptime: {uptime}; running since {start_datetime}; using multiprocessing start method: {multiprocessing_start_method}; running as user: {run_as_user}", "info")

        # Sleep the configured interval
        log(f"Sleeping main loop for REPO_CONVERTER_INTERVAL_SECONDS={environment_variables_dict['REPO_CONVERTER_INTERVAL_SECONDS']} seconds", "info")
        time.sleep(environment_variables_dict["REPO_CONVERTER_INTERVAL_SECONDS"])


if __name__ == "__main__":
    main()
