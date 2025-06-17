# TODO:

- Semaphores
    - https://medium.com/@surve.aasim/process-synchronization-using-multiprocessing-semaphore-3ca1632eed3d
    - As the main loop runs, and iterates through the list of repos (ex. 100 repos, max concurrency 10), do the other 90 sync jobs build up in an infinite queue?
    - How do we prevent adding duplicate sync jobs to the queue?

- Process management
    - Lean more about multiprocessing pools
    - Library to cleanup zombie processes, or how does Amp suggest we manage zombies?
    - Log levels
        - proc events in DEBUG logs make DEBUG level logging too noisy
        - Increase log levels of everything else?
        - Create a new lower log level named proc?
    - psutils?

- repos-to-convert.yaml
    - top level list is servers
        - details for URL, username, password
        - second level list under servers is a list of repos
            - list of repos could just be repo names
            - each repo can have its own details, such as commits to skip, branch / tag layout

- `svn log` commands
    - longest commands which seem to be timing out and causing issues are the svn log commands, which just return commit metadata
    - these commands may be duplicative
    - We may be able to make the conversion process much smoother if we can use fewer of these log commands
    - Keep an svn log file in a .git/sourcegraph directory in each repo
    - When to run the next svn log file? When the last commit ID number in the svn log file has been converted
    - Can SVN repo history be changed? Would we need to re-run svn log periodically to update the local log file cache?
    - Do we need to keep a log file of svn commands, svn server URL, repo name, execution times, response codes, response size?

## Deep Search Guidance

# What are the methods used in the sourcegraph/repo-converter repo's Python code to create child processes?

Based on my analysis of the Python code in the sourcegraph/repo-converter repository, here are the methods used to create child processes:

Primary Method: psutil.Popen()

The main method used throughout the codebase is psutil.Popen(), which is used in the custom subprocess_run() function found in both:

src/utils/cmd.py
dev/old.py (legacy version)

subprocess_to_run = psutil.Popen(
    args    = args,
    stdin   = subprocess.PIPE,
    stdout  = subprocess.PIPE,
    stderr  = subprocess.STDOUT,
    text    = True,
)

# Child Process Management Methods

The repository also includes several methods for managing child processes:

psutil.Process(pid) - Used in src/utils/cmd.py for getting process information and uptime tracking

psutil.process_iter() - Used in src/utils/cmd.py for iterating through all running processes

process.wait() - Used in src/utils/cmd.py for waiting on child processes and cleaning up zombies


## Key Benefits of This Approach

1. **Uses existing configuration**: Leverages the already-defined environment variables
2. **Thread-safe**: Uses proper locking and semaphores
3. **Robust error handling**: Ensures semaphores are always released
4. **Monitoring**: Provides visibility into current concurrency usage
5. **Flexible**: Handles different server hostnames automatically
6. **Non-blocking**: Skips repos when limits are reached rather than blocking
7. **Best practices**: Uses Python's standard threading primitives

## Usage

Users can control concurrency by setting environment variables:

```bash
# Allow maximum 5 total concurrent jobs
export MAX_CONCURRENT_CONVERSIONS_TOTAL=5

# Allow maximum 2 concurrent jobs per source server
export MAX_CONCURRENT_CONVERSIONS_PER_SERVER=2
```

This implementation provides a solid foundation that follows Python best practices while being maintainable and extensible for future needs.


# All these implementations would follow the same best practices patterns established in the concurrency management:

Semaphore-based resource control for limiting concurrent operations
Thread-safe operations with proper locking mechanisms
Graceful error handling with proper cleanup
Monitoring and observability for operational insights
Configuration-driven behavior with validation
Performance optimization through caching and pooling
These improvements would transform the codebase from having scattered TODO comments and manual resource management into a robust, production-ready system with consistent patterns throughout.



## Rearchitect

    # Parallelism
        # Re-evaluate use of psutil.Popen
            # Google how to manage a concurrency limit in Python
            # If Python has a better way to spawn child procs, clean up zombies, etc.
            # Through Amp, we can do all things
            # Find a good example repo, get it on S2, and use Deep Search to explain it


        # Read config per server
        # Enforce limit per server
            # Dumb way
                # Check the number of child procs every second
                # If fewer than [limit] processes are running
                # Then start a new child process
            # Smart way
                # Queue?

    # Add timeouts

    # Env var for a map of usernames, passwords, and servers

    # Wolfi base image for Docker / podman build
    # Add git-to-p4 converter
    # Run it in MSP, to build up our Perforce test depots from public OSS repos

## Config file

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


## SVN

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


## Build

    # Sort out tags

        # Want
            # latest: Latest release tag
            # insiders: Latest of any build
            # main: Latest commit on main
            # feature-branch: Latest commit on each feature branch
            # v0.1.1: Release tag

        # Getting
            # HEAD: On release tag build, value of BUILD_BRANCH; this build also gets the correct BUILD_TAG=v0.1.1 tag

        # Difference in GitHub Actions worker node env vars between:

            # Push to feature branch
                # gha-env-vars-push-to-branch.sh

            # PR

            # Push (merge) to main

            # Tag / release

            # workflow_dispatch
                # gha-env-vars-workflow-dispatch.sh

## Git Clone

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

    # Debug log the list of servers and repos found in config file at the start of each run?

    # If repos need non-YAML-safe characters, make repo name a key-value instead of just a key

    # Read environment variables from repos-to-convert.yaml, so the values can be changed without restarting the container

    # Container runAs user
        # src serve-git and repo-converter both run as root, which is not ideal
        # Need to create a new user on the host, add it to the host's sourcegraph group, get the UID, and configure the runas user for the containers with this UID


    # Add doc strings for each function?
        # https://www.dataquest.io/blog/documenting-in-python-with-docstrings

    # Rewrite in Go?

    # Rewrite in object oriented fashion?


# Notes:

    # psutil may not have had a recent release, may need to replace it

    # psutil requires adding gcc to the Docker image build, which adds ~4 minutes to the build time, and doubles the image size
        # It would be handy if there was a workaround without it, but multiprocessing.active_children() doesn't join the intermediate processes that Python forks

    # authors file
        # java -jar /sourcegraph/svn-migration-scripts.jar authors https://svn.apache.org/repos/asf/eagle > authors.txt
        # Kinda useful, surprisingly fast

    # git list all config
        # git -C $local_repo_path config --list

    # Decent example of converting commit messages
        # https://github.com/seantis/git-svn-trac/blob/master/git-svn-trac.py
