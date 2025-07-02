#!/usr/bin/env python3
# SVN repository handling

# from .base import Repo

# class SVNRepo(Repo):
#     """Class for SVN repository operations."""

#     def __init__(self):
#         super().__init__()

#     def clone(self):
#         """Clone an SVN repository."""
#         pass

#     def update(self):
#         """Update an SVN repository."""
#         pass

# Import repo-converter modules
from utils.context import Context
from utils.log import log
from utils import cmd, git

# Import Python standard modules
import json
import os
import random
import shutil
import time
import traceback # https://docs.python.org/3/library/traceback.html


def clone_svn_repo(ctx: Context, repo_key: str) -> None:

    # Get env vars
    max_retries     = ctx.env_vars["MAX_RETRIES"]
    src_serve_root  = ctx.env_vars['SRC_SERVE_ROOT']

    # Short name
    repo_config = ctx.repos[repo_key]

    # Debug logging for what values we have received for this repo
    log(ctx, f"{repo_key}: ctx.repos[repo_key] = {json.dumps(repo_config, indent = 4, sort_keys=True)}","debug")

    # Get config parameters read from repos-to-clone.yaml, and set defaults if they're not provided
    authors_file_path           = repo_config.get("authors-file-path"    , None    )
    authors_prog_path           = repo_config.get("authors-prog-path"    , None    )
    bare_clone                  = repo_config.get("bare-clone"           , True    )
    branches                    = repo_config.get("branches"             , None    )
    code_host_name              = repo_config.get("code-host-name"       , None    ) # Yes
    destination_git_repo_name   = repo_config.get("destination-git-repo-name"        , None    ) # Yes
    fetch_batch_size            = repo_config.get("fetch-batch-size"     , 100     ) # Yes
    git_default_branch          = repo_config.get("git-default-branch"   , "trunk" )
    git_ignore_file_path        = repo_config.get("git-ignore-file-path" , None    )
    git_org_name                = repo_config.get("git-org-name"         , None    ) # Yes
    layout                      = repo_config.get("svn-layout"           , None    ) # Yes
    password                    = repo_config.get("password"             , None    )
    repo_url                    = repo_config.get("repo-url"             , None    ) # Required
    repo_parent_url             = repo_config.get("repo-parent-url"      , None    ) # Required
    source_repo_name            = repo_config.get("source-repo-name"        , None    ) # Yes
    svn_repo_code_root          = repo_config.get("svn-repo-code-root"   , None    )
    tags                        = repo_config.get("tags"                 , None    )
    trunk                       = repo_config.get("trunk"                , None    )
    username                    = repo_config.get("username"             , None    )


    # TODO: Move .strip('/') calls to load_repos.sanitize_inputs()

    # Assemble the full URL to the repo code root path
    svn_remote_repo_code_root_url = ""

    if repo_url:
        svn_remote_repo_code_root_url = f"{repo_url.strip('/')}"

    elif repo_parent_url:
        svn_remote_repo_code_root_url = f"{repo_parent_url.strip('/')}/{source_repo_name}"

    if svn_repo_code_root:
        svn_remote_repo_code_root_url += f"/{svn_repo_code_root}"


    ## Parse config parameters into command args
    local_repo_path = f"{src_serve_root}/{code_host_name}/{git_org_name}/{destination_git_repo_name}"
    git_config_file_path = f"{local_repo_path}/.git/config"

    ## Define common command args
    arg_batch_end_revision          =           [ f"{ctx.git_config_namespace}.batch-end-revision"  ]
    arg_git                         =           [ "git", "-C", local_repo_path                  ]
    arg_git_cfg                     = arg_git + [ "config"                                      ]
    arg_git_svn                     = arg_git + [ "svn"                                         ]
    arg_svn_echo_password           = None
    arg_svn_non_interactive         =           [ "--non-interactive"                           ] # Do not prompt, just fail if the command doesn't work, only used for direct `svn` command
    arg_svn_password                =           [ "--password", password                        ] # Only used for direct `svn` commands
    arg_svn_remote_repo_code_root_url   =           [ svn_remote_repo_code_root_url                     ]
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
    cmd_git_svn_init                = arg_git_svn + [ "init"                                                    ] + arg_svn_remote_repo_code_root_url
    cmd_svn_info                    =               [ "svn", "info"                                             ] + arg_svn_non_interactive + arg_svn_remote_repo_code_root_url
    cmd_svn_log                     =               [ "svn", "log", "--xml", "--with-no-revprops"               ] + arg_svn_non_interactive + arg_svn_remote_repo_code_root_url

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
    for i in range(1, max_retries + 1):
        try:

            # Get running processes, both as a list and string
            ps_command = ["ps", "--no-headers", "-e", "--format", "pid,args"]
            running_processes = cmd.subprocess_run(ctx, ps_command, quiet=True)["output"]
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
                            pid_uptime = cmd.get_pid_uptime(int(pid))
                            if pid_uptime:

                                log_failure_message += f"running for {pid_uptime}; "

                            else:

                                # Check the process again to see if it's still running
                                log(ctx, f"{repo_key}; pid {pid} with command {args} completed while checking for concurrency collisions, will try checking again", "debug")
                                i -= 1

                            log_failure_message += f"with command: {args}; "

            if log_failure_message:

                log_failure_message = f"{repo_key}; {log_failure_message}skipping"
                log(ctx, log_failure_message, "info")
                return

            else:

                # If we got here, then there isn't another process running, and no Exceptions, so we can break out of the for loop
                break

        except Exception as exception:

            log(ctx, f"{repo_key}; Failed check {i} of {max_retries} if fetching process is already running. Exception: {type(exception)}: {exception}", "warning")

            # This stack is not the stack we think it is, it's the stack of itself, not the exception
            # stack = traceback.extract_stack()
            # (filename, line, procname, text) = stack[-1]

            # log(ctx, f"filename, line, procname, text: {filename, line, procname, text}", "debug")

            # Raising this exception kills the multiprocessing process, so it doesn't try to run this cycle
            # raise exception


    ## Check if we're in the Update state
    # Check if the git repo already exists and has the correct settings in the config file
    try:

        svn_remote_url = ""

        cmd_git_get_svn_url_output = cmd.subprocess_run(ctx, cmd_git_get_svn_url, quiet=True)

        if "output" in cmd_git_get_svn_url_output.keys() and len(cmd_git_get_svn_url_output["output"]) > 0:

            if isinstance(cmd_git_get_svn_url_output["output"], list):

                svn_remote_url = cmd_git_get_svn_url_output["output"][0]

            elif isinstance(cmd_git_get_svn_url_output["output"], str):

                svn_remote_url = cmd_git_get_svn_url_output["output"]

        if svn_remote_url in svn_remote_repo_code_root_url:

            repo_state = "update"

        else:

            log(ctx, f"{repo_key}; {' '.join(cmd_git_get_svn_url)} did not find a matching repo URL in a repo on disk, creating a new repo", "info")

    except Exception as exception:
        # Get an error when trying to git config --get svn-remote.svn.url, when the directory doesn't exist on disk
        # WARNING; karaf; failed to check git config --get svn-remote.svn.url. Exception: <class 'TypeError'>, ("'NoneType' object is not subscriptable",), 'NoneType' object is not subscriptable
        # WARNING; crunch; failed to check git config --get svn-remote.svn.url. Exception: <class 'IndexError'>, ('list index out of range',), list index out of range
        log(ctx, f"{repo_key}; failed to check git config --get svn-remote.svn.url. Exception: {type(exception)}, {exception.args}, {exception}; cmd_git_get_svn_url_output: {cmd_git_get_svn_url_output}", "warning")


    ## Run commands
    # Run the svn info command to test logging in to the SVN server, for network connectivity and credentials
    # Capture the output so we know the max revision in this repo's history
    svn_info = cmd.subprocess_run(ctx, cmd_svn_info, password, arg_svn_echo_password)
    svn_info_output_string = " ".join(svn_info["output"])

    if svn_info["return_code"] != 0:

        retries_attempted = 0

        svn_connection_failure_message_to_check_for = "Unable to connect to a repository at"

        while (
            svn_connection_failure_message_to_check_for in svn_info_output_string and
            retries_attempted < max_retries
        ):

            retries_attempted += 1
            retry_delay_seconds = random.randrange(1, 10)

            log(ctx, f"{repo_key}; Failed to connect to repo remote, retrying {retries_attempted} of max {max_retries} times, with a semi-random delay of {retry_delay_seconds} seconds", "warning")

            time.sleep(retry_delay_seconds)

            svn_info = cmd.subprocess_run(ctx, cmd_svn_info, password, arg_svn_echo_password)
            svn_info_output_string = " ".join(svn_info["output"])

        if svn_info["return_code"] != 0:

            log_failure_message = ""

            if retries_attempted == max_retries:
                log_failure_message = f"hit retry count limit {max_retries} for this run"

            log(ctx, f"{repo_key}; Failed to connect to repo remote, {log_failure_message}, skipping", "error")
            return

        else:

            log(ctx, f"{repo_key}; Successfully connected to repo remote after {retries_attempted} retries", "warning")

    log(ctx, f"svn info: {json.dumps(svn_info['output'], indent = 4, sort_keys=True)}", "debug")
    # This command should be super lightweight
    # Why does it take upwards of an hour on the customer's svn server??
    # When it takes less than a second on svn.apache.org?

    # [2025-06-30 09:05:44] build % time svn info --non-interactive https://svn.apache.org/repos/asf/crunch/site
    # Path: site
    # URL: https://svn.apache.org/repos/asf/crunch/site
    # Relative URL: ^/crunch/site
    # Repository Root: https://svn.apache.org/repos/asf
    # Repository UUID: 13f79535-47bb-0310-9956-ffa450edef68
    # Revision: 1926872
    # Node Kind: directory
    # Last Changed Author: jwills
    # Last Changed Rev: 1881028
    # Last Changed Date: 2020-08-20 10:02:07 -0600 (Thu, 20 Aug 2020)
    # [empty line]
    # svn info --non-interactive https://svn.apache.org/repos/asf/crunch/site  0.02s user 0.01s system 4% cpu 0.702 total

    # Get last changed revision for this repo
    if "Last Changed Rev: " in svn_info_output_string:
        last_changed_rev = svn_info_output_string.split("Last Changed Rev: ")[1].split(" ")[0]
    else:
        log(ctx, f"{repo_key}; 'Last Changed Rev:' not found in svn info output: {svn_info_output_string}", "error")
        return

    # Check if the previous batch end revision is the same as the last changed rev from svn info
    # If yes, we're up to date, return to the next repo, instead of forking the git svn process to do the same check
    if repo_state == "update":

        #  TypeError: 'NoneType' object is not subscriptable
        try:
            previous_batch_end_revision = cmd.subprocess_run(ctx, cmd_git_get_batch_end_revision)["output"][0]
        except Exception as exception:
            previous_batch_end_revision = "1"

        if previous_batch_end_revision == last_changed_rev:

            log(ctx, f"{repo_key}; up to date; skipping; local rev {previous_batch_end_revision}, remote rev {last_changed_rev}", "info")

            # Run git garbage collection and cleanup branches, even if repo is already up to date
            # TODO: Sort out why git gc is a command in this module, but cleaning up branches and tags is in a separate module
            cmd.subprocess_run(ctx, cmd_git_garbage_collection, quiet=True)
            git.cleanup_branches_and_tags(ctx, local_repo_path, cmd_git_default_branch, git_default_branch)

            return

        else:

            # Write and run the command
            cmd_svn_log_remaining_revs = cmd_svn_log + ["--revision", f"{previous_batch_end_revision}:HEAD"]
            svn_log = cmd.subprocess_run(ctx, cmd_svn_log_remaining_revs, password, arg_svn_echo_password)

            # Parse the output to get the number of remaining revisions
            svn_log_output_string = " ".join(svn_log["output"])
            remaining_revs_count = svn_log_output_string.count("revision=")

            # Log the results
            log(ctx, f"{repo_key}; out of date; local rev {previous_batch_end_revision}, remote rev {last_changed_rev}, {remaining_revs_count} revs remaining to catch up, fetching next batch of {min(remaining_revs_count,fetch_batch_size)} revisions; svn log command run time {svn_log['execution_time']}", "info")


    if repo_state == "create":

        log(ctx, f"{repo_key}; didn't find a local clone, creating one", "info")

        # Create the repo path if it doesn't exist
        if not os.path.exists(local_repo_path):
            os.makedirs(local_repo_path)

        if layout:
            cmd_git_svn_init   += ["--stdlayout"]

            # Warn the user if they provided an invalid value for the layout, only standard is supported
            if "standard" not in layout and "std" not in layout:
                log(ctx, f"{repo_key}; Layout shortcut provided with incorrect value {layout}, only standard is supported for the shortcut, continuing assuming standard, otherwise provide --trunk, --tags, and --branches", "warning")

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
        cmd.subprocess_run(ctx, cmd_git_svn_init, password, arg_svn_echo_password)

        # Configure the bare clone
        if bare_clone:
            cmd.subprocess_run(ctx, cmd_git_bare_clone)

        # Initialize this config with a 0 value
        cmd_git_set_batch_end_revision.append(str(0))
        cmd.subprocess_run(ctx, cmd_git_set_batch_end_revision)


    ## Back to steps we do for both Create and Update states, so users can update the below parameters without having to restart the clone from scratch
    # TODO: Check if these configs are already set the same before trying to set them

    # Set the default branch local to this repo, after init
    cmd.subprocess_run(ctx, cmd_git_default_branch)

    # Configure the authors file, if provided
    if authors_file_path:
        if os.path.exists(authors_file_path):
            cmd.subprocess_run(ctx, cmd_git_authors_file)
        else:
            log(ctx, f"{repo_key}; authors file not found at {authors_file_path}, skipping configuring it", "warning")

    # Configure the authors program, if provided
    if authors_prog_path:
        if os.path.exists(authors_prog_path):
            cmd.subprocess_run(ctx, cmd_git_authors_prog)
        else:
            log(ctx, f"{repo_key}; authors prog not found at {authors_prog_path}, skipping configuring it", "warning")

    # Configure the .gitignore file, if provided
    if git_ignore_file_path:
        if os.path.exists(git_ignore_file_path):
            shutil.copy2(git_ignore_file_path, local_repo_path)
        else:
            log(ctx, f"{repo_key}; .gitignore file not found at {git_ignore_file_path}, skipping configuring it", "warning")

    # Batch processing
    batch_start_revision    = None
    batch_end_revision      = None

    try:

        # Get the revision number to start with
        if repo_state == "update":

            # Try to retrieve repo-converter.batch-end-revision from git config
            # previous_batch_end_revision = git config --get repo-converter.batch-end-revision
            # Need to fail gracefully
            previous_batch_end_revision = cmd.subprocess_run(ctx, cmd_git_get_batch_end_revision)["output"]

            if previous_batch_end_revision:

                batch_start_revision = int(" ".join(previous_batch_end_revision)) + 1

        if repo_state == "create" or batch_start_revision == None:

            # If this is a new repo, get the first changed revision number for this repo from the svn server log
            cmd_svn_log_batch_start_revision = cmd_svn_log + ["--limit", "1", "--revision", "1:HEAD"]
            svn_log_batch_start_revision = cmd.subprocess_run(ctx, cmd_svn_log_batch_start_revision, password, arg_svn_echo_password)["output"]
            batch_start_revision = int(" ".join(svn_log_batch_start_revision).split("revision=\"")[1].split("\"")[0])

        # Get the revision number to end with
        if batch_start_revision:

            # Get the batch size'th revision number for the rev to end this batch range
            cmd_svn_log_batch_end_revision = cmd_svn_log + ["--limit", str(fetch_batch_size), "--revision", f"{batch_start_revision}:HEAD"]
            cmd_svn_log_batch_end_revision_output = cmd.subprocess_run(ctx, cmd_svn_log_batch_end_revision, password, arg_svn_echo_password)["output"]

            try:

                # While we're at it, update the batch starting rev to the first real rev number after the previous end rev +1
                batch_start_revision = int(" ".join(cmd_svn_log_batch_end_revision_output).split("revision=\"")[1].split("\"")[0])

                # Reverse the output so we can get the last revision number
                cmd_svn_log_batch_end_revision_output.reverse()
                batch_end_revision = int(" ".join(cmd_svn_log_batch_end_revision_output).split("revision=\"")[1].split("\"")[0])

            except IndexError as exception:
                log(ctx, f"{repo_key}; IndexError when getting batch start or end revisions for batch size {fetch_batch_size}, skipping this run to retry next run", "warning")
                return

                # log(ctx, f"{repo_key}; IndexError when getting batch start or end revisions for batch size {fetch_batch_size}; running the fetch without the batch size limit; exception: {type(exception)}, {exception.args}, {exception}", "warning")
                #  <class 'IndexError'>, ('list index out of range',), list index out of range
                # Need to handle the issue where revisions seem to be out of order on the server

        # If we were successful getting both starting and ending revision numbers
        if batch_start_revision and batch_end_revision:

            # Use them
            cmd_git_svn_fetch += ["--revision", f"{batch_start_revision}:{batch_end_revision}"]

    except Exception as exception:

        # Log a warning if this fails, and run the fetch without the --revision arg
        # log(ctx, f"{repo_key}; failed to get batch start or end revision for batch size {fetch_batch_size}; running the fetch without the batch size limit; exception: {type(exception)}, {exception.args}, {exception}", "warning")

        log(ctx, f"{repo_key}; failed to get batch start or end revision for batch size {fetch_batch_size}; skipping this run to retry next run; exception: {type(exception)}, {exception.args}, {exception}", "warning")
        return

    # Delete duplicate lines from the git config file, before the fetch
    # hoping that it increases our chances of a successful fetch
    # Passing in repo_state, as a file not found error for repo_state=create is not a problem, but is a problem for repo_state=update
    git.deduplicate_git_config_file(ctx, git_config_file_path, repo_state)

    # Start the fetch
    cmd_git_svn_fetch_string_may_have_batch_range = " ".join(cmd_git_svn_fetch)
    log(ctx, f"{repo_key}; fetching with {cmd_git_svn_fetch_string_may_have_batch_range}", "info")
    git_svn_fetch_result = cmd.subprocess_run(ctx, cmd_git_svn_fetch, password, password)

    # If the fetch succeed, and if we have a batch_end_revision
    if git_svn_fetch_result["return_code"] == 0 and batch_end_revision:

        # Store the ending revision number
        cmd_git_set_batch_end_revision.append(str(batch_end_revision))
        cmd.subprocess_run(ctx, cmd_git_set_batch_end_revision)

        log(ctx, f"{repo_key}; git fetch complete; run time {git_svn_fetch_result['execution_time']}", "info")

    else:

        log(ctx, f"{repo_key}; git fetch failed; run time {git_svn_fetch_result['execution_time']}", "error")

    # Run Git garbage collection before handing off to cleanup branches and tags
    cmd.subprocess_run(ctx, cmd_git_garbage_collection)

    git.cleanup_branches_and_tags(ctx, local_repo_path, cmd_git_default_branch, git_default_branch)
