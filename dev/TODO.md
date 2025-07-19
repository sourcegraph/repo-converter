# TODO

## Observability

- Implement OpenTelemetry

- Find a tool to search / filter through logs
    - See Slack thread with Eng
    - Amped the `dev/query_logs.py` script in the meantime

- Build up log event context, ex. canonical logs
    - Store job metadata in a dict, key is pid?
    - And be able to retrieve this context in cmd.log_process_status()
        - What little data do we have from a child process reap event, which we can lookup in the dict?
        - grandparent pid?

- Add to the status monitor thread loop:
    - Details of each running job
        - Number of commits at the beginning
        - Number of commits added in the current job
        - "svn-remote.svn.branches-maxRev"
        - retries_attempted
        - Commit date of the most recently converted revision
        - Commit date of the SVN Last Changed Rev

- Enhance error events with automatic error context capture and correlation IDs
    - Remote server response errors, ex. svn: E175012: Connection timed out
    - Decorators and context managers for logging context?

- Amp's suggestion
    - Context Managers: Git operations and command execution use context managers to automatically inject relevant metadata for all logs within their scope.
    - Decorator Pattern: Command execution decorator automatically captures all command-related data (args, timing, stdout/stderr, exit codes).
    - This architecture uses a context stack pattern where different operational contexts (git operations, command execution) automatically push their metadata, making all relevant data available to every log statement within that context.

- Set up log schema and workspace settings for RedHat's [YAML](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml) VS Code extension

## SVN

### Stability

- Maybe we don't need to handle batch processing, just infinite retries?
    - We still need rev numbers to show progress of conversion jobs
    - It'd be much simpler if we could use the data already stored by `git svn fetch`, than have to query this data from the server
    - These rev numbers are available:
        - Done - Last Changed Rev from `svn info` output
        - Done - Last converted rev from `git for-each-ref -limit=1` output, and / or the `.git/svn/something/origin/branch/.commit-map-repo-uuid` binary file
            - Would the size of this file tell us how many commits have been converted
        - Done - Count of commits from local git repo history
        - Done - Last rev checked, from the `.git/svn/.metadata` file
    - So we have all the data we need, what's stopping us from using it instead of `svn log` data?
    - But wait... isn't the situation we started in?
        - Jobs timed out, because they were trying to boil the ocean / convert the entire repo in one go
        - This was a big problem, because the script only ran in series, so it'd hold up all the other repos
        - The script now runs in parallel, so other job slots can continue processing
    - Initial scan through repo rev index, at `--log-window-size n` number of revs per network request, can take a really long time
        - Running the `svn log 1:HEAD --limit 1` command didn't take this long

- `git svn fetch --revision [BASE:HEAD] --log-window-size [100]`
    - Does actually commit each individual revision as its converted
        - This may not be visible, as the git.garbage_collection() and git.cleanup_branches_and_tags() functions have to run to make the branches visible (local)
    - Absolutely intolerant of invalid revs in the `--revisions` range
        - ex. if the start of the range is prior in the local repo's history, it'll just exit 0 with no output, and no changes
    - BASE
        - If any local commits, BASE is the most recent commit (local git HEAD)
        - If no local commits, BASE defaults to 0, which is super inefficient, as it has to make (first_rev/log-window-size) requests to the SVN server, just to find the starting rev
    - HEAD
        - (remote)
        - Matches "Last Changed Rev" from the `svn info` command output
    - log-window-size
        - For each HTTP request to the Subversion server, the number of revs to query for

- `cat .git/svn/.metadata`
    ```
    ; This file is used internally by git-svn
    ; You should not have to edit it
    [svn-remote "svn"]
            reposRoot = https://svn.apache.org/repos/asf
            uuid = 13f79535-47bb-0310-9956-ffa450edef68
            branches-maxRev = 1886214
            tags-maxRev = 1886140
    ```
    - branches-maxRev
    - tags-maxRev
        - The last revs that git svn has checked for branches / tags
        - Future iterations can start at this number, to prevent duplicate work, checking old revs
        - If the user changes the branches in scope, this number must be reset

### Performance

- SVN commands hanging
    - Add a timeout in run_subprocess() for hanging svn info and svn log commands, if data isn't transferring

- Different approach: Sync SVN-to-SVN, then convert from local SVN server
    - https://kevin.deldycke.com/2012/how-to-create-local-copy-svn-repository
    - Create an empty local SVN repository:
        ```shell
        rm -rf ./svn-repo
        svnadmin create ./svn-repo
        sed -i 's/# password-db = passwd/password-db = passwd/' ./svn-repo/conf/svnserve.conf
        echo "kevin = kevin" >> ./svn-repo/conf/passwd
        kill `ps -ef | grep svnserve | grep -v grep | awk '{print $2}'`
        svnserve --daemon --listen-port 3690 --root ./svn-repo
        ```
    - Give the synchronization utility permission on the local repository:
        ```shell
        echo "#!/bin/sh" > ./svn-repo/hooks/pre-revprop-change
        chmod 755 ./svn-repo/hooks/pre-revprop-change
        ```
    - Initialize the synchronization between the remote server (https://svn.example.com/svn/internal-project) and the local SVN (svn://localhost:3690):
        ```shell
        svnsync init --sync-username "kevin" --sync-password "kevin" --source-username "kevin@example.com" --source-password "XXXXXX" svn://localhost:3690 https://svn.example.com/svn/internal-project
        ```
    - Once all of this configuration is done, we can start dumping the content of the remote repository to our local copy:
        ```shell
        svnsync --non-interactive --sync-username "kevin" --sync-password "kevin" --source-username "kevin@example.com" --source-password "XXXXXX" sync svn://localhost:3690
        ```

### Other

- .gitignore files
    - `git svn create-ignore`
    - `git svn show-ignore`
    - https://git-scm.com/docs/git-svn#Documentation/git-svn.txt-emcreate-ignoreem

- Test layout tags and branches as lists / arrays

## Config

- Move the config schema to a separate YAML file
    - Bake it into the image
    - Read it into Context on container startup, so the `sanitize_repos_to_convert` function can update it, to make it available to `check_required_fields`
    - Provide, for each field:
        - Name
        - Description
        - Default values
        - Valid data types
        - Required? (ex. either repo-url or repo-parent-url)
        - Valid parents (global / server / repo), so child keys can be validated that they're under a valid parent key
        - Usage
        - Examples

- Implement proper type validation with clear error messages for config file inputs

- Create server-specific concurrency semaphore from repos-to-convert value, if present

- Env vars vs config file
    - Env vars
        - Service-oriented, ex. log level
        - Cannot change without restarting the container
        - Create env var for a map so creds don't need to be stored in files
            - server
            - username
            - password
    - repos-to-convert.yaml
        - Content-oriented
        - List of repos to convert
        - Can change without restarting the container

## Processes

- How do I get more information about the child PID which was reaped in these lines, in `./src/utils/signal_handler.py`?

    ```python
    if os.WIFEXITED(status) and os.WEXITSTATUS(status) != 0:
        # "message": "SIGCHLD handler reaped child PID 10747 with exit code 129",
        log(ctx, f"SIGCHLD handler reaped child PID {pid} with exit code {os.WEXITSTATUS(status)}", "warning")
    ```
    - Maintain a list of processes, with their metadata, from when they're launched, and updated on an interval, then look up the PID's information in the signal handler from the list
        - Track PIDs when launching: Store process metadata (command, start time, purpose) in a dict when creating child processes
        - Cross-reference with active processes: Check if the PID exists in ctx.active_repo_conversion_processes
    - Use process monitoring libraries?

- Prevent stack traces during shutdown; from Amp:
    - The SIGTERM signals are received across different cycles (11, 0, 1) because:
        - Signal handler registers itself recursively: In signal_handler.py:19, the handler is registered as a lambda that calls itself
        - Process group kill triggers more signals: When the handler calls os.killpg() at line 39, it sends SIGTERM to all processes in the group, including itself
        - Multiple threads/processes receive signals: Each active process/thread receives its own SIGTERM and logs the "Received signal" message
    - Stack Trace During Shutdown occur because:
        - Signal handler called during JSON logging: The signal handler interrupts the logging process while it's serializing JSON data (line 51-52 in traceback)
        - Recursive signal handling: The handler tries to log while already handling a signal, creating a nested call
        - Multiprocessing cleanup fails: The FileNotFoundError at line 100 indicates the multiprocessing manager's socket connection was already closed when trying to access self.active_jobs[server_name]
    - Root Causes
        - Non-reentrant signal handling: The signal handler isn't designed to handle recursive calls safely
        - Race condition: The multiprocessing manager shuts down before all processes finish cleanup
        - Signal propagation: os.killpg() creates a cascade of signals across the process group
    - The application does eventually shut down gracefully, but the multiple signal receptions and stack traces indicate the shutdown process could be more robust.

- Multiprocessing / state / zombie cleanup
    - Implement better multiprocessing status and state tracking
        - Multiprocessing pools?
    - Integrate subprocess methods together
        - State tracking, in ctx.child_procs = {}
        - Cleanup of zombie processes, and richer process status updates, in cmd.status_update_and_cleanup_zombie_processes()?
        - svn._check_if_conversion_is_already_running_in_another_process() vs concurrency_manager.acquire_job_slot()
        - Clean up of process state

- Add to the process status check and cleanup function to
    - Get the last lines of stdout from a running process,
    - instead of just wait with a timeout of 0.1,
    - use communicate() with a timeout and read the stdout from the return value,
    - catch the timeout exception
    - May require tracking process objects in a dict, which would prevent processes from getting auto-cleaned, which may result in higher zombie numbers

- Implement better error handling for process management

## Builds

- GitHub Actions build tags
    - Want
        - latest: Latest release tag
        - insiders: Latest of any build
        - main: Latest commit on main
        - feature-branch: Latest commit on each feature branch
        - v0.1.1: Release tag
    - Getting
        - HEAD: On release tag build, value of BUILD_BRANCH; this build also gets the correct BUILD_TAG=v0.1.1 tag
    - Difference in GitHub Actions worker node env vars between:
        - Push to feature branch
            - gha-env-vars-push-to-branch.sh
        - PR
            -
        - Push (merge) to main
            -
        - Tag / release
            -
        - workflow_dispatch
            - gha-env-vars-workflow-dispatch.sh
- GitHub Actions cleanup jobs
- Wolfi Python base image for Docker / podman build
- Container runAs user
    - It seems like the only way this works for both Podman and Docker Compose, is to:
        - Bake the image with a specific UID/GID,
        - and change the app service user account's UID/GID on the host OS to match
    - Changed the UID of the service account on the host to 10001, and GID to 10002
    - I hope I'm wrong on this limitation, adding this to the TODO list to figure out later

## Dev

- Add proper doc strings to all classes and methods
    - https://www.dataquest.io/blog/documenting-in-python-with-docstrings

## Expansion

- Implement TODOs strewn around the code

- Add git-to-p4 converter
    - Run it in MSP, to build up our Perforce test depots from public OSS repos

- Git clone
    - Move Git SSH clone Bash script into this containers
    - See if the GitPython module fetches the repo successfully, or has a way to clone multiple branches
        - Fetch (just the default branch)
        - Fetch all branches
        - Clone all branches
    - From the git remote --help
        - Imitate git clone but track only selected branches
            - mkdir project.git
            - cd project.git
            - git init
            - git remote add -f -t master -m master origin git://example.com/git.git/
            - git merge origin

## Notes

- Authors file
    - java -jar /sg/svn-migration-scripts.jar authors https://svn.apache.org/repos/asf/eagle > authors.txt
    - Kinda useful, surprisingly fast

- git list all config for a repo
    - git -C $local_repo_path config --list

- Decent example of converting commit messages
    - https://github.com/seantis/git-svn-trac/blob/master/git-svn-trac.py
