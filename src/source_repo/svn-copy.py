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


def convert(ctx: Context) -> None:
    """
    Entrypoint / main logic / orchestration function
    """

    # Declare the reason string in the job context
    ctx.job["job"]["reason"] = ""

    # Extract repo conversion job config values from the repos list in ctx,
    # and set default values for required but undefined configs
    config = extract_repo_config_and_set_default_values(ctx)

    # Build sets of repeatable commands to use each external CLI
    svn_commands = build_svn_cli_commands(ctx, config)
    git_commands = build_git_cli_commands(ctx, config)

    # Check if a repo cloning job is already in progress
    if check_if_conversion_is_already_running_in_another_process(ctx, config, git_commands, svn_commands):
        return

    # Determine repository state (create / update)
    repo_state = determine_repo_state(ctx, config, git_commands)

    # Validate SVN connection
    svn_result = validate_svn_connection(ctx, svn_commands)
    if svn_result.get("error"):
        return

    # Get revision information
    revision_info = get_revision_info(ctx, svn_result, git_commands)
    if revision_info.get("error"):
        return

    # Handle up-to-date repos early
    if revision_info.get("up_to_date"):
        log_recent_commits = ctx.env_vars["LOG_RECENT_COMMITS"]
        if log_recent_commits > 0:
            # Output the n most recent commits to visually verify the local git repo is up to date with the remote repo
            cmd_svn_log_recent_revs = svn_commands['cmd_svn_log'] + ["--limit", f"{log_recent_commits}"]
            ctx.job["svn_log_output"] = cmd.run_subprocess(ctx, cmd_svn_log_recent_revs, config['password'], svn_commands['arg_svn_echo_password'], quiet=True, name="svn_log_recent_commits")["output"]
            log(ctx, f"LOG_RECENT_COMMITS={log_recent_commits}", "debug")
            # Remove the svn_log_output from the job context dict, so it doesn't get logged again in subsequent logs
            ctx.job.pop("svn_log_output")

        # Run git garbage collection and cleanup branches, even if repo is already up to date
        git.garbage_collection(ctx, config['local_repo_path'])
        git.cleanup_branches_and_tags(ctx, config['local_repo_path'], git_commands['cmd_git_default_branch'], config['git_default_branch'])
        return

    # Handle update state with remaining revisions logging
    if ctx.job["job"]["repo_state"] == "update" and not revision_info.get("up_to_date"):
        # Log remaining revisions info for update state
        cmd_svn_log_remaining_revs = svn_commands['cmd_svn_log'] + ["--revision", f"{revision_info['previous_batch_end_revision']}:HEAD"]
        svn_log = cmd.run_subprocess(ctx, cmd_svn_log_remaining_revs, config['password'], svn_commands['arg_svn_echo_password'], name="[REDACTED:password]")

        # Parse the output to get the number of remaining revs
        svn_log_output_string = " ".join(svn_log["output"])
        remaining_revs_count = svn_log_output_string.count("revision=")
        fetching_batch_count = min(remaining_revs_count, config['fetch_batch_size'])

        # Log the results
        ctx.job["job"]["repo_state"] = "Updating"
        ctx.job["job"]["reason"] = "Out of date"
        ctx.job["job"]["remaining_revs"] = remaining_revs_count
        ctx.job["job"]["fetching_batch_count"] = fetching_batch_count

        log(ctx, f"Out of date; updating", "info")

    # Initialize repository if needed
    if ctx.job["job"]["repo_state"] == "create":
        initialize_git_repo(ctx, config, git_commands)

    # Configure repository
    configure_git_repo(ctx, config, git_commands)

    # Calculate batch revisions
    batch_info = calculate_batch_revisions(ctx, svn_commands, config, revision_info)
    if batch_info.get("error"):
        return

    # Execute the fetch
    execute_git_svn_fetch(ctx, config, git_commands, batch_info)


def extract_repo_config_and_set_default_values(ctx: Context) -> dict:
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


def build_svn_cli_commands(ctx: Context, config: dict) -> dict:
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
        'arg_svn_echo_password': True if password else None
    }


def build_git_cli_commands(ctx: Context, config: dict) -> dict:
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


def check_if_conversion_is_already_running_in_another_process(
        ctx: Context,
        config: dict,
        git_commands: dict,
        svn_commands: dict
    ) -> bool:
    """
    Check if any repo conversion-related processes are currently running in the container

    Return True if yes, to avoid multiple concurrent conversion jobs on the same repo

    TODO: This function may no longer be needed due to the new semaphore handling,
    or this logic could be moved to the acquire_job_slot function, as it may be applicable to other repo types
    """

    repo_key = ctx.job["job"]["repo_key"]
    max_retries = ctx.env_vars["MAX_RETRIES"]
    local_repo_path = config['local_repo_path']

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


def determine_repo_state(ctx: Context, config: dict, git_commands: dict) -> str:
    """
    Determine if repo is in 'create' or 'update' state
    """

    local_repo_path = config['local_repo_path']
    svn_remote_repo_code_root_url = config['svn_remote_repo_code_root_url']

    # Default to create state
    ctx.job["job"]["repo_state"] = "create"

    try:
        svn_remote_url = ""
        cmd_git_get_svn_url_output = cmd.run_subprocess(ctx, git_commands['cmd_git_get_svn_url'], quiet=True, name="cmd_git_get_svn_url_output")

        if "output" in cmd_git_get_svn_url_output.keys() and len(cmd_git_get_svn_url_output["output"]) > 0:
            if isinstance(cmd_git_get_svn_url_output["output"], list):
                svn_remote_url = cmd_git_get_svn_url_output["output"][0]
            elif isinstance(cmd_git_get_svn_url_output["output"], str):
                svn_remote_url = cmd_git_get_svn_url_output["output"]

        if svn_remote_url in svn_remote_repo_code_root_url:
            ctx.job["job"]["repo_state"] = "update"
        else:
            log(ctx, f"Repo not found on disk, initializing new repo", "info")

    except Exception as exception:
        log(ctx, f"failed to check git config --get svn-remote.svn.url. Exception: {type(exception)}, {exception.args}, {exception}; cmd_git_get_svn_url_output: {cmd_git_get_svn_url_output}", "warning")

    return ctx.job["job"]["repo_state"]


def validate_svn_connection(ctx: Context, svn_commands: dict) -> dict:
    """
    Validate SVN connection and return SVN info
    """

    max_retries = ctx.env_vars["MAX_RETRIES"]
    password = svn_commands.get('password')
    arg_svn_echo_password = svn_commands['arg_svn_echo_password']

    svn_info = cmd.run_subprocess(ctx, svn_commands['cmd_svn_info'], password, arg_svn_echo_password, name="[REDACTED:password]")
    svn_info_output_string = " ".join(svn_info["output"])

    if svn_info["return_code"] != 0:
        retries_attempted = 0
        svn_connection_failure_message_to_check_for = "Unable to connect to a repository at"

        while (svn_connection_failure_message_to_check_for in svn_info_output_string and
               retries_attempted < max_retries):

            retries_attempted += 1
            retry_delay_seconds = random.randrange(1, 10)

            log(ctx, f"Failed to connect to repo remote, retrying {retries_attempted} of max {max_retries} times, with a semi-random delay of {retry_delay_seconds} seconds", "warning")

            time.sleep(retry_delay_seconds)

            svn_info = cmd.run_subprocess(ctx, svn_commands['cmd_svn_info'], password, arg_svn_echo_password, name="[REDACTED:password]")
            svn_info_output_string = " ".join(svn_info["output"])

        if svn_info["return_code"] != 0:
            log_failure_message = ""
            if retries_attempted == max_retries:
                log_failure_message = f"hit retry count limit {max_retries} for this run"

            log(ctx, f"Failed to connect to repo remote, {log_failure_message}, skipping", "error")
            return {"error": True, "svn_info": svn_info}
        else:
            log(ctx, f"Successfully connected to repo remote after {retries_attempted} retries", "warning")

    return {"error": False, "svn_info": svn_info, "svn_info_output_string": svn_info_output_string}


def get_revision_info(ctx: Context, svn_result: dict, git_commands: dict) -> dict:
    """
    Extract revision information from SVN info
    """

    svn_info_output_string = svn_result["svn_info_output_string"]

    # Get last changed revision for this repo
    if "Last Changed Rev: " in svn_info_output_string:
        last_changed_rev = int(svn_info_output_string.split("Last Changed Rev: ")[1].split(" ")[0])
        ctx.job["job"]["last_changed_rev"] = int(last_changed_rev)
    else:
        log(ctx, f"'Last Changed Rev:' not found in svn info output: {svn_info_output_string}", "error")
        return {"error": True}

    revision_info = {"last_changed_rev": last_changed_rev, "error": False}

    # Check if we're up to date (for update state)
    if ctx.job["job"]["repo_state"] == "update":
        try:
            previous_batch_end_revision = int(cmd.run_subprocess(ctx, git_commands['cmd_git_get_batch_end_revision'], name="cmd_git_get_batch_end_revision")["output"][0])
        except Exception as exception:
            previous_batch_end_revision = 1

        ctx.job["job"]["local_rev"] = int(previous_batch_end_revision)
        revision_info["previous_batch_end_revision"] = previous_batch_end_revision

        if previous_batch_end_revision == last_changed_rev:
            ctx.job["job"]["repo_state"] = "Skipping"
            ctx.job["job"]["reason"] = "Up to date"
            log(ctx, f"Up to date; skipping", "info")
            revision_info["up_to_date"] = True
        else:
            revision_info["up_to_date"] = False

    return revision_info


def calculate_batch_revisions(ctx: Context, svn_commands: dict, config: dict, revision_info: dict) -> dict:
    """
    Calculate batch start and end revisions for fetching
    """

    fetch_batch_size = config['fetch_batch_size']
    password = config['password']
    arg_svn_echo_password = svn_commands['arg_svn_echo_password']
    cmd_svn_log = svn_commands['cmd_svn_log']

    batch_start_revision = None
    batch_end_revision = None

    try:
        # Get the revision number to start with
        if ctx.job["job"]["repo_state"] == "update":
            previous_batch_end_revision = revision_info.get("previous_batch_end_revision")
            if previous_batch_end_revision:
                batch_start_revision = int(previous_batch_end_revision) + 1

        if ctx.job["job"]["repo_state"] == "create" or batch_start_revision == None:
            # Get the first changed revision number for this repo from the svn server log
            cmd_svn_log_batch_start_revision = cmd_svn_log + ["--limit", "1", "--revision", "1:HEAD"]
            svn_log_batch_start_revision = cmd.run_subprocess(ctx, cmd_svn_log_batch_start_revision, password, arg_svn_echo_password, name="[REDACTED:password]")["output"]
            batch_start_revision = int(" ".join(svn_log_batch_start_revision).split("revision=\"")[1].split("\"")[0])

        # Get the revision number to end with
        if batch_start_revision:
            cmd_svn_log_batch_end_revision = cmd_svn_log + ["--limit", str(fetch_batch_size), "--revision", f"{batch_start_revision}:HEAD"]
            cmd_svn_log_batch_end_revision_output = cmd.run_subprocess(ctx, cmd_svn_log_batch_end_revision, password, arg_svn_echo_password, name="[REDACTED:password]")["output"]

            try:
                # Update the batch starting rev to the first real rev number after the previous end rev +1
                batch_start_revision = int(" ".join(cmd_svn_log_batch_end_revision_output).split("revision=\"")[1].split("\"")[0])
                ctx.job["job"]["batch_start_revision"] = batch_start_revision

                # Reverse the output so we can get the last revision number
                cmd_svn_log_batch_end_revision_output.reverse()
                batch_end_revision = int(" ".join(cmd_svn_log_batch_end_revision_output).split("revision=\"")[1].split("\"")[0])
                ctx.job["job"]["batch_end_revision"] = batch_end_revision

            except IndexError as exception:
                log(ctx, f"IndexError when getting batch start or end revs for batch size {fetch_batch_size}, skipping this run to retry next run", "warning")
                return {"error": True}

    except Exception as exception:
        log(ctx, f"failed to get batch start or end revision for batch size {fetch_batch_size}; skipping this run to retry next run; exception: {type(exception)}, {exception.args}, {exception}", "warning")
        return {"error": True}

    return {
        "error": False,
        "batch_start_revision": batch_start_revision,
        "batch_end_revision": batch_end_revision
    }


def initialize_git_repo(ctx: Context, config: dict, git_commands: dict) -> None:
    """
    Initialize a new Git repository
    """

    local_repo_path = config['local_repo_path']
    layout = config['layout']
    trunk = config['trunk']
    tags = config['tags']
    branches = config['branches']
    bare_clone = config['bare_clone']
    password = config['password']

    log(ctx, f"Didn't find a local clone, initializing a new local clone", "info")

    # Create the repo path if it doesn't exist
    if not os.path.exists(local_repo_path):
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
    cmd.run_subprocess(ctx, cmd_git_svn_init, password, True if password else None, name="[REDACTED:password]")

    # Configure the bare clone
    if bare_clone:
        cmd.run_subprocess(ctx, git_commands['cmd_git_bare_clone'], name="cmd_git_bare_clone")

    # Initialize this config with a 0 value
    cmd_git_initialize_batch_end_revision_with_zero_value = git_commands['cmd_git_set_batch_end_revision'] + [str(0)]
    cmd.run_subprocess(ctx, cmd_git_initialize_batch_end_revision_with_zero_value, name="cmd_git_initialize_batch_end_revision_with_zero_value")


def configure_git_repo(ctx: Context, config: dict, git_commands: dict) -> None:
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
            config_already_set = git.get_config(ctx, local_repo_path, git_config_key)
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


def validate_git_repository_state(ctx: Context, local_repo_path: str) -> tuple[bool, str]:
    """
    Validate that the Git repository is in a valid state
    """

    checks = []

    # Check if git repo is valid
    cmd_git_status = ["git", "-C", local_repo_path, "status", "--porcelain"]
    result = cmd.run_subprocess(ctx, cmd_git_status, quiet=True, name="git_status")
    checks.append(("git_status", result["return_code"] == 0))

    # Check if HEAD exists
    cmd_git_head = ["git", "-C", local_repo_path, "rev-parse", "HEAD"]
    result = cmd.run_subprocess(ctx, cmd_git_head, quiet=True, name="git_head")
    checks.append(("git_head", result["return_code"] == 0))

    # Check if git-svn metadata exists
    cmd_git_svn_info = ["git", "-C", local_repo_path, "svn", "info"]
    result = cmd.run_subprocess(ctx, cmd_git_svn_info, quiet=True, name="git_svn_info")
    checks.append(("git_svn_info", result["return_code"] == 0))

    failed_checks = [name for name, passed in checks if not passed]

    if failed_checks:
        return False, f"Repository state validation failed: {failed_checks}"

    return True, "Repository state validation passed"


def execute_git_svn_fetch(ctx: Context, config: dict, git_commands: dict, batch_info: dict) -> dict:
    """
    Execute the git svn fetch operation
    """

    local_repo_path = config['local_repo_path']
    password = config['password']
    batch_start_revision = batch_info.get("batch_start_revision")
    batch_end_revision = batch_info.get("batch_end_revision")

    cmd_git_svn_fetch = git_commands['cmd_git_svn_fetch'].copy()

    # If we have batch revisions, use them
    if batch_start_revision and batch_end_revision:
        cmd_git_svn_fetch += ["--revision", f"{batch_start_revision}:{batch_end_revision}"]

    # Delete duplicate lines from the git config file, before the fetch
    if ctx.job["job"]["repo_state"] == "update":
        git.deduplicate_git_config_file(ctx, local_repo_path)

    # Start the fetch
    cmd_git_svn_fetch_string_may_have_batch_range = " ".join(cmd_git_svn_fetch)
    log(ctx, f"fetching with {cmd_git_svn_fetch_string_may_have_batch_range}", "info")
    git_svn_fetch_result = cmd.run_subprocess(ctx, cmd_git_svn_fetch, password, True if password else None, name="[REDACTED:password]")

    # Validate repository state
    git_repository_state_valid, git_repository_state_message = validate_git_repository_state(ctx, local_repo_path)
    log(ctx, f"validate_git_repository_state result: {git_repository_state_valid}; message: {git_repository_state_message}", "debug")

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

    # If the fetch succeeded and we have a batch_end_revision
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
