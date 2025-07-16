# TODO

## Logging

- Objective:
    - Make the conversion process go faster, and more stable, in the customer's environment
- How do we achieve this?
    - Identify which commands are taking a long time, or failing, and why
- Okay, how?
    - Done
        - Implement structured logging
        - Update customer production
        - Collect log events
        - Query log events from JSON lines to CSV, using `dev/query_logs.py`
        - Analyze log events to understand which commands are taking the longest (`svn log`, by a mile)
    - In Progress
        - Implement a better way to run the `svn log` command, to take less time
    - To Do
        - Analyze failure events:
            - Which commands are failing most?
            - Why?
        - Implement OpenTelemetry

- Find a tool to search / filter through logs
    - See Slack thread with Eng
    - Amped the `dev/query_logs.py` script in the meantime

- Build up log event context, ex. canonical logs
        - Store job metadata in a dict, key is pid?
    - And be able to retrieve this context in cmd.log_process_status()
        - What little data do we have from a child process reap event, which we can lookup in the dict?
        - grandparent pid?

- Enhance error events with automatic error context capture and correlation IDs
    - Remote server response errors, ex. svn: E175012: Connection timed out
    - Decorators and context managers for logging context?

- Log a repo status event at the end of the svn.py module
    - Remote
        - SVN
            - Revs remaining to convert, if LOG_REMAINING_REVS
            - Total rev count, if LOG_REMAINING_REVS
    - Local
        - Git
            - Difference between svn_info last changed date, and git last commit date
    - Last run's status (success / fail)
    - Progress (% of revs converted)

- Amp's suggestion
    - Context Managers: Git operations and command execution use context managers to automatically inject relevant metadata for all logs within their scope.
    - Decorator Pattern: Command execution decorator automatically captures all command-related data (args, timing, stdout/stderr, exit codes).
    - This architecture uses a context stack pattern where different operational contexts (git operations, command execution) automatically push their metadata, making all relevant data available to every log statement within that context.

- Set up log schema and workspace settings for RedHat's [YAML](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml) VS Code extension

## SVN

### Stability

- `git svn fetch`
    - Commits not getting committed to the local repo
    - Not entirely sure if svn is blocking me

- `svn log` commands
    - Longest commands, which seem to be timing out and causing issues
    - What do we use them for? Why?
        - Limitations of `git svn fetch`:
            - Does not have a --batch-size arg, but does have a --revisions (range) arg
            - Does not commit synced changes to the local git repo until the job completes, so we have to run it in batches
        - The big one: Count all revs remaining to convert, as a progress indicator - Disabled this by default
        - The small one: Get first and last rev numbers to start and end this batch - Seems to be necessary, but combined into one, and limited to batch size
        - The smallest one: Log recent commits, to visually verify a successful fetch - Disabled by default
    - We may be able to make the conversion process much smoother if we can use fewer of these log commands
        - Keep the output revision numbers from `git svn log --xml` commands in a file on disk
        - Append to this file when there are new revisions, so getting counts of revisions in each repo is slow once, fast many times
        - Use an XML parsing library or regex matches to extract revision numbers, but store as JSON in the file
    - The problem with the `git svn` CLI, is that failures still exit 0, so we have to bubble wrap around it

    - Compare svn log file against `git log` output, to ensure that each of the SVN revision numbers is found in the git log, and raise an error if any are missing or out of order

    - When to run the next svn log command?
        - When the last commit ID number in the svn log file has been converted
    - Can SVN repo history be changed?
        - Would we need to re-run svn log periodically to update the local log file?

- Implement more accurate conversion job success validation before updating git config with latest rev
- Add better error handling for subcommands with specific error types
- Use git.get_config(), git.set_config(), and GitPython more extensively?

### Performance

- Dynamically reduce batch size on timeouts
    - If timeout error, retry with half the batch size
    - If the batch size succeeded, persist the batch size for the one repo, with a comment as to why the change was made

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
- If list of repos is blank in repos-to-convert, try and parse the list from the server?

## Config

- Move the config schema to a separate YAML file, bake it into the image, read it into Context on container startup, and provide for each field:
    - Name
    - Description
    - Default values
    - Valid data types
    - Required? (ex. either repo-url or repo-parent-url)
    - Valid parents (global / server / repo), so child keys can be validated that they're under a valid parent key
    - Usage
    - Examples

- Make `repos_to_convert_fields` a part of Context, so the `sanitize_repos_to_convert` function can save it, to make it available to `check_required_fields`

- Implement proper type validation with clear error messages for config file inputs

- Create server-specific concurrency semaphore from repos-to-convert value, if present

- Add a fetch-interval-seconds config to repos-to-convert.yaml file
    - Under global, server, or repo config
    - For each repo in the repos_dict
        - Add a "next sync time" field in the dict
    - convert_svn_repos loop
        - Try and read it
                - next_fetch_time = repo_key.get(next-fetch-time, None)
        - If it's defined and in the future, skip this run
            - if next_fetch_time
                - if next_fetch_time >= time.now()
                    - Log.debug(repo_key next fetch time is: yyyy-mm-dd HH:MM:SS, skipping)
                    - continue
                - Else
                    - Log.debug(repo_key next fetch time was: yyyy-mm-dd HH:MM:SS, fetching)
        - Doing this before forking the process reduces zombies and debug process log noise for repos which are already up to date, and don’t get a ton of commits
    - convert_svn_repo
        - Set the next fetch time to None, so the forking loop doesn't fork again for this repo fetch interval
            - repo_key[next-fetch-time] = None
        - Check if this repo has a fetch interval defined
            - fetch_interval_seconds = repo_key.get(fetch-interval-seconds, None)
            - If yes, calculate and store the next fetch time
            - If fetch_interval_seconds
                - repo_key[next-fetch-time] = fetch_interval_seconds + time.now()

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
    - Maintain a list of processes, with their metadata, from when they're launched, and updated on an interval, then look up that information in the signal handler
        - Track PIDs when launching: Store process metadata (command, start time, purpose) in a dict when creating child processes
        - Cross-reference with active processes: Check if the PID exists in ctx.active_repo_conversion_processes
    - Use process monitoring libraries

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
    - Learn more about multiprocessing pools
    - Implement better multiprocessing status and state tracking
    - Integrate subprocess methods together
        - State tracking, in ctx.child_procs = {}
        - Cleanup of zombie processes
        - Clean up of process state
    - Improve zombie process detection and cleanup
        - Library to cleanup zombie processes, or how does Amp suggest we manage zombies?

- Add to the process status check and cleanup function to
    - Get the last lines of stdout from a running process,
    - instead of just wait with a timeout of 0.1,
    - use communicate() with a timeout and read the stdout from the return value,
    - catch the timeout exception
    - May require tracking process objects in a dict, which would prevent processes from getting auto-cleaned, which may result in higher zombie numbers

- Implement better error handling for process management

## Builds

- GitHub Action build tags
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
