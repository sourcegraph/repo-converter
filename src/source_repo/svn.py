#!/usr/bin/env python3
# Convert a Subversion repo to Git

# Import repo-converter modules
from utils.context import Context
from utils.log import log
from utils import cmd, git

# Import Python standard modules
import os
import random
import shutil
import time

# TODO: Sort out which values are in which dicts, prevent duplication
# dicts for:
    # ctx, including repo_config subdict, and job subdict for logging
    # commands, separate from ctx, as they do not need to be shared / logged
    # if config dict is needed, merge commands dict into config dict
    # Pass information around in these dicts ^, not other return values / dicts / strings / etc.

# Repo states:
    # Exists and is valid / doesn't exist or is invalid
    # Up to date / out of date

# Optimize control flow for:
    # Fewest svn remote commands
    # Easiest reading / maintenance
    # Fewest local commands


def convert(ctx: Context) -> None:
    """
    Entrypoint / main logic / orchestration function
    """

    # Declare the reason string in the job context
    ctx.job["job"]["reason"] = ""

    # Extract repo conversion job config values from the repos list in ctx,
    # and set default values for required but undefined configs
    config = _extract_repo_config_and_set_default_values(ctx)

    # Build sets of repeatable commands to use each external CLI
    svn_commands = _build_svn_cli_commands(ctx, config)
    git_commands = _build_git_cli_commands(ctx, config)

    # Check if a repo cloning job is already in progress
    if _check_if_conversion_is_already_running_in_another_process(ctx, config, git_commands, svn_commands):
        return

    # Test connection to the SVN server
    ### EXTERNAL COMMAND: svn info ###
    svn_info = _test_connection_and_credentials(ctx, svn_commands)

    # If the connection failed, return now
    if not svn_info:
        return

    # Get revision information from the svn_info output
    remote_last_changed_rev = _get_remote_last_changed_rev_from_svn_info(ctx, svn_info)

    # If the svn_info output doesn't include the last changed rev, there's probably a server problem
    if not remote_last_changed_rev:
        return

    # Check if the local repo exists and is valid
    # or doesn't exist / is invalid,
    # thus we need to create / recreate it
    if not _check_if_repo_exists_locally(ctx, config, git_commands):

        # If the repo doesn't exist locally, initialize it
        _initialize_git_repo(ctx, config, git_commands)

     # Update repo config
    _configure_git_repo(ctx, config, git_commands)

    # Check if the local repo is already up to date
    if _check_if_repo_already_up_to_date(ctx, config):

        # If the repo already exists, and is already up to date, then exit early
        # TODO: Set ctx.job attributes for repo state / up to date

        ### EXTERNAL COMMAND: svn log ###
        _log_recent_commits(ctx, config, git_commands, svn_commands)
        _cleanup(ctx, config, git_commands)
        return

    ### EXTERNAL COMMAND: svn log ###
    # This is the big one, to count all revs remaining
    _log_number_of_revs_out_of_date(ctx, config, svn_commands)

    # Calculate revision range for this fetch
    ### EXTERNAL COMMAND: svn log --limit batch-size ###
    if not _calculate_batch_revisions(ctx, svn_commands, config):
        return

    # Execute the fetch
    ### EXTERNAL COMMAND: git svn fetch ###
    _execute_git_svn_fetch(ctx, config, git_commands)

    # Cleanup and exit
    _cleanup(ctx, config, git_commands)


def _extract_repo_config_and_set_default_values(ctx: Context) -> dict:
    """
    Extract repo configuration parameters from the Context object
    """

    # Get the repo key from the job context
    repo_key = ctx.job["job"]["repo_key"]

    # Short name for repo config dict
    repo_config = ctx.repos[repo_key]

    # Debug logging for the config values we have received for this repo
    ctx.job["job"]["repo_config"] = repo_config
    log(ctx, "Repo config", "debug")

    # Get config parameters read from repos-to-clone.yaml, and set defaults if they're not provided
    config = {
        'authors_file_path'        : repo_config.get("authors-file-path",        None),
        'authors_prog_path'        : repo_config.get("authors-prog-path",        None),
        'bare_clone'               : repo_config.get("bare-clone",               True),
        'branches'                 : repo_config.get("branches",                 None),
        'code_host_name'           : repo_config.get("code-host-name",           None),
        'destination_git_repo_name': repo_config.get("destination-git-repo-name",None),
        'fetch_batch_size'         : repo_config.get("fetch-batch-size",         100),
        'git_default_branch'       : repo_config.get("git-default-branch",       "trunk"),
        'git_ignore_file_path'     : repo_config.get("git-ignore-file-path",     None),
        'git_org_name'             : repo_config.get("git-org-name",             None),
        'layout'                   : repo_config.get("svn-layout",               None),
        'password'                 : repo_config.get("password",                 None),
        'repo_url'                 : repo_config.get("repo-url",                 None),
        'repo_parent_url'          : repo_config.get("repo-parent-url",          None),
        'source_repo_name'         : repo_config.get("source-repo-name",         None),
        'svn_repo_code_root'       : repo_config.get("svn-repo-code-root",       None),
        'tags'                     : repo_config.get("tags",                     None),
        'trunk'                    : repo_config.get("trunk",                    None),
        'username'                 : repo_config.get("username",                 None)
    }

    # Assemble the full URL to the repo code root path on the remote SVN server
    svn_remote_repo_code_root_url = ""

    if config['repo_url']:
        svn_remote_repo_code_root_url = f"{config['repo_url']}"
    elif config['repo_parent_url']:
        svn_remote_repo_code_root_url = f"{config['repo_parent_url']}/{config['source_repo_name']}"

    if config['svn_repo_code_root']:
        svn_remote_repo_code_root_url += f"/{config['svn_repo_code_root']}"

    config['svn_remote_repo_code_root_url'] = svn_remote_repo_code_root_url

    # Set local_repo_path
    src_serve_root = ctx.env_vars['SRC_SERVE_ROOT']
    local_repo_path = f"{src_serve_root}/{config['code_host_name']}/{config['git_org_name']}/{config['destination_git_repo_name']}"
    config['local_repo_path'] = local_repo_path
    ctx.job["job"]["local_repo_path"] = local_repo_path

    return config


def _build_svn_cli_commands(ctx: Context, config: dict) -> dict:
    """
    Build commands for svn cli
    As lists of strings
    """

    username = config['username']
    password = config['password']
    svn_remote_repo_code_root_url = config['svn_remote_repo_code_root_url']

    # Define common command args
    arg_svn_non_interactive = ["--non-interactive"]
    arg_svn_password = ["--password", password] if password else []
    arg_svn_username = ["--username", username] if username else []
    arg_svn_remote_repo_code_root_url = [svn_remote_repo_code_root_url]

    # Build base commands
    cmd_svn_info = ["svn", "info"] + arg_svn_non_interactive + arg_svn_remote_repo_code_root_url
    cmd_svn_log = ["svn", "log", "--xml", "--with-no-revprops"] + arg_svn_non_interactive + arg_svn_remote_repo_code_root_url

    # Add authentication if provided
    if username:
        cmd_svn_info += arg_svn_username
        cmd_svn_log += arg_svn_username

    if password:
        cmd_svn_info += arg_svn_password
        cmd_svn_log += arg_svn_password

    return {
        'cmd_svn_info': cmd_svn_info,
        'cmd_svn_log': cmd_svn_log,
    }


def _build_git_cli_commands(ctx: Context, config: dict) -> dict:
    """
    Build commands for git cli
    As lists of strings

    This may be somewhat confusing, as `git svn` commands use the git cli
    """

    local_repo_path = config['local_repo_path']
    git_default_branch = config['git_default_branch']
    svn_remote_repo_code_root_url = config['svn_remote_repo_code_root_url']
    username = config['username']

    # Define common command args
    arg_batch_end_revision = [f"{ctx.git_config_namespace}.batch-end-revision"]
    arg_git = ["git", "-C", local_repo_path]
    arg_git_cfg = arg_git + ["config"]
    arg_git_svn = arg_git + ["svn"]
    arg_svn_remote_repo_code_root_url = [svn_remote_repo_code_root_url]
    arg_svn_username = ["--username", username] if username else []

    # Define commands
    cmd_git_bare_clone = arg_git_cfg + ["core.bare", "true"]
    cmd_git_default_branch = arg_git + ["symbolic-ref", "HEAD", f"refs/heads/{git_default_branch}"]
    cmd_git_garbage_collection = arg_git + ["gc"]
    cmd_git_get_batch_end_revision = arg_git_cfg + ["--get"] + arg_batch_end_revision
    cmd_git_get_svn_url = arg_git_cfg + ["--get", "svn-remote.svn.url"]
    cmd_git_set_batch_end_revision = arg_git_cfg + ["--replace-all"] + arg_batch_end_revision
    cmd_git_svn_fetch = arg_git_svn + ["fetch"]
    cmd_git_svn_init = arg_git_svn + ["init"] + arg_svn_remote_repo_code_root_url

    # Modify commands based on config parameters
    if username:
        cmd_git_svn_init += arg_svn_username
        cmd_git_svn_fetch += arg_svn_username

    return {
        'cmd_git_bare_clone': cmd_git_bare_clone,
        'cmd_git_default_branch': cmd_git_default_branch,
        'cmd_git_garbage_collection': cmd_git_garbage_collection,
        'cmd_git_get_batch_end_revision': cmd_git_get_batch_end_revision,
        'cmd_git_get_svn_url': cmd_git_get_svn_url,
        'cmd_git_set_batch_end_revision': cmd_git_set_batch_end_revision,
        'cmd_git_svn_fetch': cmd_git_svn_fetch,
        'cmd_git_svn_init': cmd_git_svn_init
    }


def _check_if_conversion_is_already_running_in_another_process(
        ctx: Context,
        config: dict,
        git_commands: dict,
        svn_commands: dict
    ) -> bool:
    """
    Check if any repo conversion-related processes are currently running in the container

    Return True if yes, to avoid multiple concurrent conversion jobs on the same repo

    TODO: This function may no longer be needed due to the new semaphore handling,
    or this logic could be vastly simplified (ex. _test_connection_and_credentials),
    and moved to the acquire_job_slot function, as it may be applicable to other repo types
    """

    local_repo_path = config['local_repo_path']
    max_retries = ctx.env_vars["MAX_RETRIES"]
    repo_key = ctx.job["job"]["repo_key"]

    # Range 1 - max_retries + 1 for human readability in logs
    for i in range(1, max_retries + 1):

        try:

            # Get running processes, both as a list and string
            ps_command = ["ps", "--no-headers", "-e", "--format", "pid,args"]
            running_processes_list = cmd.run_subprocess(ctx, ps_command, quiet=True, name="ps")["output"]
            running_processes_string = " ".join(running_processes_list)

            # Define the list of strings we're looking for in the running processes' commands
            cmd_git_svn_fetch_string = " ".join(git_commands['cmd_git_svn_fetch'])
            cmd_git_garbage_collection_string = " ".join(git_commands['cmd_git_garbage_collection'])
            cmd_svn_log_string = " ".join(svn_commands["cmd_svn_log"])
            process_name = f"convert_{repo_key}"

            # In priority order
            concurrency_error_strings_and_messages = [
                (cmd_git_svn_fetch_string, "Previous fetching process still"),
                (cmd_git_garbage_collection_string, "Git garbage collection process still"),
                (cmd_svn_log_string, "Previous svn log process still"),
                (process_name, "Previous process still"),
                # Potential problem: if one repo's name is a substring of another repo's name
                (local_repo_path, "Local repo path in process"),
            ]

            log_failure_message = ""

            # Loop through the list of strings we're looking for, to check the running processes for each of them
            for concurrency_error_string_and_message in concurrency_error_strings_and_messages:

                # If this string we're looking for is found
                if concurrency_error_string_and_message[0] in running_processes_string:

                    # Find which process it's in
                    for i in range(len(running_processes_list)):

                        running_process = running_processes_list[i]
                        pid, args = running_process.lstrip().split(" ", 1)

                        # If it's this process, and this process hasn't already matched one of the previous concurrency errors
                        if (
                            concurrency_error_string_and_message[0] in args and
                            pid not in log_failure_message
                        ):

                            # Add its message to the string
                            log_failure_message += f"{concurrency_error_string_and_message[1]} running in pid {pid}; "

                            # Calculate its running time
                            # Quite often, processes will complete when get_pid_uptime() checks them,
                            # if this is the case, then try this check again
                            pid_uptime = cmd.get_pid_uptime(int(pid))
                            if pid_uptime:
                                log_failure_message += f"running for {pid_uptime}; "
                            else:
                                log(ctx, f"pid {pid} with command {args} completed while checking for concurrency collisions, will try checking again", "debug")
                                i -= 1

                            log_failure_message += f"with command: {args}; "

            if log_failure_message:
                ctx.job["job"]["reason"] = log_failure_message
                log(ctx, "Skipping repo conversion job", "info")
                return True
            else:
                # No processes running, can proceed, break out of the max_retries loop
                break

        except Exception as exception:
            log(ctx, f"Failed check {i} of {max_retries} if fetching process is already running. Exception: {type(exception)}: {exception}", "warning")

    return False


def _test_connection_and_credentials(ctx: Context, svn_commands: dict) -> dict:
    """
    Run the svn info command to test:
    - Network connectivity to the SVN server
    - Authentication credentials, if provided

    Capture the output, so we can later extract the current remote rev from it

    The svn info command should be quite lightweight, and return very quickly
    """

    # Prepare variables
    cmd_svn_info = svn_commands['cmd_svn_info']
    max_retries = ctx.env_vars["MAX_RETRIES"]
    password = svn_commands.get("password","")
    retries_attempted = 0

    while True:

        # Run the command, capture the output
        svn_info = cmd.run_subprocess(ctx, cmd_svn_info, password, name=f"svn_info_{retries_attempted}")

        # If the command exited successfully, return the process output dict
        if svn_info["return_code"] == 0:

            if retries_attempted > 0:
                log(ctx, f"Successfully connected to repo remote after {retries_attempted} retries", "warning")

            return svn_info

        # If we've hit the max_retries limit, return here
        elif retries_attempted >= max_retries:

            log(ctx, f"Failed to connect to repo remote, reached max retries {max_retries}", "error")

            return None

        # Otherwise, prepare for retry
        else:

            retries_attempted += 1

            # Log the failure
            retry_delay_seconds = random.randrange(1, 5)
            log(ctx, f"Failed to connect to repo remote, retrying {retries_attempted} of max {max_retries} times, with a semi-random delay of {retry_delay_seconds} seconds", "debug")
            time.sleep(retry_delay_seconds)

        # Repeat the loop


def _get_remote_last_changed_rev_from_svn_info(ctx: Context, svn_info: dict) -> bool:
    """
    Extract revision information from SVN info
    """

    # Combine / cast the output lines into a string
    svn_info_output_string = " ".join(svn_info.get("output",""))

    # Get last changed revision for this SVN repo from the svn info output
    if "Last Changed Rev: " in svn_info_output_string:

        remote_last_changed_rev = int(svn_info_output_string.split("Last Changed Rev: ")[1].split(" ")[0])
        ctx.job["job"]["remote_last_changed_rev"] = int(remote_last_changed_rev)
        return True

    else:

        log(ctx, f"Skipping; Last Changed Rev not found in svn info output: {svn_info_output_string}", "error")
        return False


def _check_if_repo_exists_locally(ctx: Context, config: dict, git_commands: dict) -> str:
    """
    Check if the local repo exists and we need to update it,
    or if it doesn't exist, or it's invalid, and we need to create / recreate it

    Create:
        State:
            The directory doesn't already exist
            The repo      doesn't already exist
        How did we get here:
            First run of the script
            New repo was added to the repos-to-convert.yaml file
            Repo was deleted from disk
        Approach:
            Harder to test for the negative, so let's:
            - Assume we're in the Create state,
            - Check if the repo exists and is valid, then we're in the Update state

    Update:
        State:
            Repo already exists, with a valid configuration
        How did we get here:
            A fetch job was previously run, but is not currently running
        Approach:
            Check if we're in the update state, then set ctx.job["job"]["repo_create_or_update"] = "update"

    """

    local_repo_path = config['local_repo_path']
    svn_remote_repo_code_root_url = config['svn_remote_repo_code_root_url']

    # Default to create state
    repo_create_or_update = "create"

    # try:

        # TODO: Replace this with git.get_config()
        # Run the cmd_git_get_svn_url command, to try getting the svn URL from the local git repo's config file
        # if this passes, then we're in the update state,
        # otherwise, the repo either doesn't exist on disk, or is in an invalid state and needs to be recreated
        # svn_remote_url = ""
        # cmd_git_get_svn_url_output = cmd.run_subprocess(ctx, git_commands['cmd_git_get_svn_url'], quiet=True, name="cmd_git_get_svn_url_output")

    svn_url = git.get_config(ctx, local_repo_path, "svn-remote.svn.url")
    svn_url = " ".join(svn_url)

    if svn_url and svn_url in svn_remote_repo_code_root_url:
        repo_create_or_update = "update"

        # # If the command returned any output
        # if cmd_git_get_svn_url_output.get("output",""):

        #     # The output should always be a list of strings
        #     if isinstance(cmd_git_get_svn_url_output["output"], list):
        #         svn_remote_url = cmd_git_get_svn_url_output["output"][0]

        #     # But this check was in here for some reason
        #     else:
        #         svn_remote_url = cmd_git_get_svn_url_output["output"]

        #     # If the URL from the local repo git config file is a substring of the repo code root URL,
        #     # then we know that we have a valid local repo
        #     if svn_remote_url in svn_remote_repo_code_root_url:
        #         repo_create_or_update = "update"

    else:
        log(ctx, f"Repo not found on disk, initializing new repo", "info")

    # except Exception as exception:
    #     log(ctx, f"failed to check {git_commands['cmd_git_get_svn_url']}. Exception: {type(exception)}, {exception.args}, {exception}; cmd_git_get_svn_url_output: {cmd_git_get_svn_url_output}", "warning")


    ctx.job["job"]["repo_create_or_update"] = repo_create_or_update

    return repo_create_or_update


def _initialize_git_repo(ctx: Context, config: dict, git_commands: dict) -> None:
    """
    Initialize a new Git repository
    """

    # TODO: Move all the arg / command assembly to another function

    local_repo_path = config['local_repo_path']
    layout = config['layout']
    trunk = config['trunk']
    tags = config['tags']
    branches = config['branches']
    bare_clone = config['bare_clone']
    password = config['password']

    log(ctx, f"Didn't find a local clone, initializing a new local clone", "info")

    # If the directory does exist, then it's not a valid git repo, and needs to be destroyed and recreated
    if os.path.exists(local_repo_path):
        os.rmdir(local_repo_path)

    # Created the needed dirs
    os.makedirs(local_repo_path)

    cmd_git_svn_init = git_commands['cmd_git_svn_init'].copy()

    if layout:
        cmd_git_svn_init += ["--stdlayout"]
        # Warn the user if they provided an invalid value for the layout
        if "standard" not in layout and "std" not in layout:
            log(ctx, f"Layout shortcut provided with incorrect value {layout}, only standard is supported for the shortcut, continuing assuming standard, otherwise provide --trunk, --tags, and --branches", "warning")

    # There can only be one trunk
    if trunk:
        cmd_git_svn_init += ["--trunk", trunk]

    # Tags and branches can either be single strings or lists of strings
    if tags:
        if isinstance(tags, str):
            cmd_git_svn_init += ["--tags", tags]
        if isinstance(tags, list):
            for tag in tags:
                cmd_git_svn_init += ["--tags", tag]

    if branches:
        if isinstance(branches, str):
            cmd_git_svn_init += ["--branches", branches]
        if isinstance(branches, list):
            for branch in branches:
                cmd_git_svn_init += ["--branches", branch]

    # Initialize the repo
    # TODO: git svn shouldn't need a password to initialize a repo?
    cmd.run_subprocess(ctx, cmd_git_svn_init, password, name="cmd_git_svn_init")

    # Configure the bare clone
    if bare_clone:
        cmd.run_subprocess(ctx, git_commands['cmd_git_bare_clone'], name="cmd_git_bare_clone")

    # Initialize this config with a 0 value
    cmd_git_initialize_batch_end_revision_with_zero_value = git_commands['cmd_git_set_batch_end_revision'] + [str(0)]
    cmd.run_subprocess(ctx, cmd_git_initialize_batch_end_revision_with_zero_value, name="cmd_git_initialize_batch_end_revision_with_zero_value")


def _configure_git_repo(ctx: Context, config: dict, git_commands: dict) -> None:
    """
    Configure Git repository settings
    """

    local_repo_path = config['local_repo_path']
    authors_file_path = config['authors_file_path']
    authors_prog_path = config['authors_prog_path']
    git_ignore_file_path = config['git_ignore_file_path']

    # Set the default branch local to this repo, after init
    cmd.run_subprocess(ctx, git_commands['cmd_git_default_branch'], name="cmd_git_default_branch")

    # Set repo configs, as a list of tuples [(git config key, git config value),]
    git_config_paths = [
        ("svn.authorsfile", authors_file_path),
        ("svn.authorsProg", authors_prog_path),
    ]

    for git_config_key, git_config_value in git_config_paths:

        if git_config_value:

            # Check if these configs are already set the same before trying to set them

            # TODO: Test this
            config_already_set = git.get_config(ctx, local_repo_path, git_config_key)
            config_already_set = " ".join(config_already_set)
            config_already_set_matches = config_already_set == git_config_value
            path_exists = os.path.exists(git_config_value)

            if path_exists and config_already_set_matches:
                continue
            elif path_exists and not config_already_set_matches:
                git.set_config(ctx, local_repo_path, git_config_key, git_config_value)
            elif not path_exists and config_already_set_matches:
                log(ctx, f"{git_config_key} already set, but file doesn't exist, unsetting it", "warning")
                git.unset_config(ctx, local_repo_path, git_config_key)
            elif not path_exists:
                log(ctx, f"{git_config_key} not found at {git_config_value}, skipping configuring it", "warning")

    # Copy the .gitignore file into place, if provided
    if git_ignore_file_path:
        if os.path.exists(git_ignore_file_path):
            # Always copy, to overwrite if any changes were made
            shutil.copy2(git_ignore_file_path, local_repo_path)
        else:
            log(ctx, f".gitignore file not found at {git_ignore_file_path}, skipping copying it", "warning")


def _check_if_repo_already_up_to_date(ctx: Context, config: dict) -> bool:
    """
    Get the local_last_batch_end_revision from the local git repo

    Compare it against remote_last_changed_rev from the svn info output
    """

    remote_last_changed_rev = ctx.job["job"].get("remote_last_changed_rev","")
    local_repo_path = config['local_repo_path']

    # get_config() returns a list of strings, cast it into an int
    local_last_batch_end_revision = git.get_config(ctx, local_repo_path, f"{ctx.git_config_namespace}.batch-end-revision")
    local_last_batch_end_revision = int(" ".join(local_last_batch_end_revision))

    if local_last_batch_end_revision:

        ctx.job["job"]["local_last_batch_end_revision"] = local_last_batch_end_revision

    else:

        ctx.job["job"]["local_last_batch_end_revision"] = 0

    if local_last_batch_end_revision == remote_last_changed_rev:
        return True

    else:
        return False


def _log_recent_commits(ctx: Context, config: dict, git_commands: dict, svn_commands: dict) -> None:
    """
    If the repo exists and is already up to date,
    run these steps to cleanup,
    then return
    """

    local_repo_path = config['local_repo_path']

    log_recent_commits = ctx.env_vars["LOG_RECENT_COMMITS"]

    if log_recent_commits > 0:

        # Output the n most recent commits to visually verify the local git repo is up to date with the remote repo
        cmd_svn_log_recent_revs = svn_commands['cmd_svn_log'] + ["--limit", f"{log_recent_commits}"]
        ctx.job["svn_log_output"] = cmd.run_subprocess(ctx, cmd_svn_log_recent_revs, config['password'], quiet=True, name="svn_log_recent_commits")["output"]

        log(ctx, f"LOG_RECENT_COMMITS={log_recent_commits}", "debug")

        # Remove the svn_log_output from the job context dict, so it doesn't get logged again in subsequent logs
        ctx.job.pop("svn_log_output")


def _log_number_of_revs_out_of_date(ctx: Context, config: dict, svn_commands: dict) -> None:
    """
    Run the svn log command to count the total number of revs out of date

    TODO: Eliminate this, or make it much more efficient
    """

    local_last_batch_end_revision = ctx.job["job"]["local_last_batch_end_revision"]

    # Log remaining revisions info for update state
    cmd_svn_log_remaining_revs = svn_commands['cmd_svn_log'] + ["--revision", f"{local_last_batch_end_revision}:HEAD"]
    svn_log = cmd.run_subprocess(ctx, cmd_svn_log_remaining_revs, config['password'], name="svn_log_remaining_revs")

    # Parse the output to get the number of remaining revs
    svn_log_output_string = " ".join(svn_log["output"])
    remaining_revs_count = svn_log_output_string.count("revision=")
    fetching_batch_count = min(remaining_revs_count, config['fetch_batch_size'])

    # Log the results
    ctx.job["job"]["reason"] = "Out of date"
    ctx.job["job"]["remaining_revs"] = remaining_revs_count
    ctx.job["job"]["fetching_batch_count"] = fetching_batch_count

    log(ctx, f"Out of date; updating", "info")


def _calculate_batch_revisions(ctx: Context, svn_commands: dict, config: dict) -> dict:
    """
    Run the svn log command to calculate batch start and end revisions for fetching

    TODO: Eliminate this, or make it much more efficient
    """

    cmd_svn_log = svn_commands['cmd_svn_log']
    fetch_batch_size = config['fetch_batch_size']
    local_last_batch_end_revision = int(ctx.job["job"]["local_last_batch_end_revision"])
    password = config['password']
    this_batch_end_revision = None
    this_batch_start_revision = 0

    # Pick a revision number to start with; may or may not be a real rev number
    this_batch_start_revision = local_last_batch_end_revision + 1

    # Run the svn log command to get real revision numbers for this batch
    cmd_svn_log_batch_rev = cmd_svn_log + ["--limit", str(fetch_batch_size), "--revision", f"{this_batch_start_revision}:HEAD"]
    cmd_svn_log_batch_rev_result = cmd.run_subprocess(ctx, cmd_svn_log_batch_rev, password, name="cmd_svn_log_batch_rev")

    cmd_svn_log_batch_rev_output = cmd_svn_log_batch_rev_result.get("output","")

    if cmd_svn_log_batch_rev_result["return_code"] == 0 and cmd_svn_log_batch_rev_output:

        # Update the this batch's starting rev to the first real rev number after the previous end rev
        this_batch_start_revision = int(" ".join(cmd_svn_log_batch_rev).split("revision=\"")[1].split("\"")[0])
        ctx.job["job"]["batch_start_rev"] = this_batch_start_revision

        # Reverse the output so we can get the last revision number
        cmd_svn_log_batch_rev_output.reverse()
        this_batch_end_revision = int(" ".join(cmd_svn_log_batch_rev_output).split("revision=\"")[1].split("\"")[0])
        ctx.job["job"]["batch_end_revision"] = this_batch_end_revision

        return True

    else:

        log(ctx, "Failed to calculate batch revs", "error")
        return False


def _execute_git_svn_fetch(ctx: Context, config: dict, git_commands: dict, batch_info: dict) -> dict:
    """
    Execute the git svn fetch operation
    """

    batch_end_revision      = ctx.job["job"]["batch_end_rev"]
    batch_start_revision    = ctx.job["job"]["batch_start_rev"]
    cmd_git_svn_fetch       = git_commands['cmd_git_svn_fetch'].copy()
    local_repo_path         = config['local_repo_path']
    password                = config['password']

    # If we have batch revisions, use them
    if batch_start_revision and batch_end_revision:
        cmd_git_svn_fetch += ["--revision", f"{batch_start_revision}:{batch_end_revision}"]

    # Delete duplicate lines from the git config file, before the fetch
    git.deduplicate_git_config_file(ctx, local_repo_path)

    # Start the fetch
    log(ctx, f"fetching with {' '.join(cmd_git_svn_fetch)}", "info")
    git_svn_fetch_result = cmd.run_subprocess(ctx, cmd_git_svn_fetch, password, name="cmd_git_svn_fetch")

    # Validate repository state
    # git_repository_state_valid, git_repository_state_message = _validate_git_repository_state(ctx, local_repo_path)
    # log(ctx, f"validate_git_repository_state result: {git_repository_state_valid}; message: {git_repository_state_message}", "debug")

    # Check for errors
    error_messages = [
        "Can't create session", "Unable to connect to a repository at URL", "Connection refused",
        "Connection timed out", "SSL handshake failed", "Authentication failed",
        "Authorization failed", "Invalid credentials", "Error running context",
        "Repository not found", "Path not found", "Invalid repository URL",
        "fatal:", "error:", "abort:", "Permission denied", "No space left on device",
        "svn: E", "Working copy locked", "Repository is locked",
    ]

    success = True
    for error_message in error_messages:
        if error_message in str(git_svn_fetch_result["output"]):
            success = False
            if "reason" not in ctx.job["job"].keys():
                ctx.job["job"]["reason"] = f"{error_message}"
            else:
                ctx.job["job"]["reason"] += f" {error_message}"

    # If the fetch succeeded and we have a this_batch_end_revision
    if git_svn_fetch_result["return_code"] == 0 and batch_end_revision:
        # Store the ending revision number
        cmd_git_set_batch_end_revision_with_value = git_commands['cmd_git_set_batch_end_revision'] + [str(batch_end_revision)]
        cmd.run_subprocess(ctx, cmd_git_set_batch_end_revision_with_value, name="cmd_git_set_batch_end_revision_with_value")
        log(ctx, f"git svn fetch complete", "info")
    else:
        log(ctx, f"git svn fetch failed", "error")

    # Run Git garbage collection and cleanup
    git.garbage_collection(ctx, local_repo_path)
    git.cleanup_branches_and_tags(ctx, local_repo_path, git_commands['cmd_git_default_branch'], config['git_default_branch'])

    return git_svn_fetch_result


# def _validate_git_repository_state(ctx: Context, local_repo_path: str) -> tuple[bool, str]:
#     """
#     Validate that the Git repository is in a valid state
#     """

#     checks = []

#     # Check if git repo is valid
#     cmd_git_status = ["git", "-C", local_repo_path, "status", "--porcelain"]
#     result = cmd.run_subprocess(ctx, cmd_git_status, quiet=True, name="git_status")
#     checks.append(("git_status", result["return_code"] == 0))

#     # Check if HEAD exists
#     cmd_git_head = ["git", "-C", local_repo_path, "rev-parse", "HEAD"]
#     result = cmd.run_subprocess(ctx, cmd_git_head, quiet=True, name="git_head")
#     checks.append(("git_head", result["return_code"] == 0))

#     # Check if git-svn metadata exists
#     cmd_git_svn_info = ["git", "-C", local_repo_path, "svn", "info"]
#     result = cmd.run_subprocess(ctx, cmd_git_svn_info, quiet=True, name="git_svn_info")
#     checks.append(("git_svn_info", result["return_code"] == 0))

#     failed_checks = [name for name, passed in checks if not passed]

#     if failed_checks:
#         return False, f"Repository state validation failed: {failed_checks}"

#     return True, "Repository state validation passed"


def _cleanup(ctx: Context, config: dict, git_commands: dict) -> None:
    """
    Groups up any other functions needed to clean up before exit
    """

    local_repo_path = config['local_repo_path']

    # Run git garbage collection and cleanup branches, even if repo is already up to date
    git.garbage_collection(ctx, local_repo_path)
    git.cleanup_branches_and_tags(ctx, local_repo_path, git_commands['cmd_git_default_branch'], config['git_default_branch'])
