# TODO:

## Rearchitect

    # Get it compiling / working
        # Imports
        # repos_to_convert.py rethink how sanitization / secrets are added to set
        # Take Amp's suggestion of making better use of Python-native logging
        # Object-oriented design where it makes sense

    # Parallelism
        # Re-evaluate use of os.fork, if multi-processing has a better way to spawn child procs, clean up zombies, etc.
        # Read config per server
        # Enforce limit per server


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

    # psutil requires adding gcc to the Docker image build, which adds ~4 minutes to the build time, and doubles the image size
        # It would be handy if there was a workaround without it, but multiprocessing.active_children() doesn't join the intermediate processes that Python forks

    # authors file
        # java -jar /sourcegraph/svn-migration-scripts.jar authors https://svn.apache.org/repos/asf/eagle > authors.txt
        # Kinda useful, surprisingly fast

    # git list all config
        # git -C $local_repo_path config --list

    # Decent example of converting commit messages
        # https://github.com/seantis/git-svn-trac/blob/master/git-svn-trac.py
