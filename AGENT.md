# AI Agent Guidelines for repo-converter

- The purpose of this project is to convert repos from other repo types (ex. Subversion) to Git
- It runs in a Podman container
- src/main.py is the entrypoint for the container
- The usage of this project is described to users in `./README.md` and `./docs/repo-converter.md`

## Build/Test Commands

- Build and start all containers: `./build/build.sh`
- Build and start all containers, and follow the repo-converter container's logs: `./build/build.sh f`

## Code Style Guidelines

- Python version: 3.13.2
- Imports: local modules first, standard libs second, then third-party libs with URLs in comments
- Variables: Snake case (e.g., `local_repo_path`)
- Error handling: Use try/except blocks with specific exception types
- Logging: Use the custom `log(ctx, "message", "log_level")` function with appropriate levels
- Functions: Snake case for function names
- Security: the log function calls the `redact()` function before logging, to ensure no credentials are leaked in logs
- Documentation: Use Python best practices for docstrings
- Comments: Use `#` for comments, and add lots of comments

## Design Facts

When a user runs the command `svn info https://svn.apache.org/repos/asf/lucene`, the output shows:
```
Path: lucene
URL: https://svn.apache.org/repos/asf/lucene
Relative URL: ^/lucene
Repository Root: https://svn.apache.org/repos/asf
Repository UUID: 13f79535-47bb-0310-9956-ffa450edef68
Revision: 1927289
Node Kind: directory
Last Changed Author: vajda
Last Changed Rev: 1921508
Last Changed Date: 2024-10-23 13:00:39 +0000 (Wed, 23 Oct 2024)"
```

Reorganized for readability:
```
URL: https://svn.apache.org/repos/asf/lucene            <- Just the URL from the command
Repository Root: https://svn.apache.org/repos/asf       <- The URL to the svn repo's root directory
Repository UUID: 13f79535-47bb-0310-9956-ffa450edef68   <- The svn server assigns a UUID for each repo
Path: lucene                                            <- The subdirectory path, from the repo root, to the directory in the URL passed into the `svn info` command
Revision: 1927289                                       <- The current tip of the repo's revision number index
Last Changed Rev: 1921508                               <- The last revision number which included a change in the requested URL
Last Changed Date: 2024-10-23 13:00:39 +0000 (Wed...    <- The date of the last revision  which included a change in the requested URL
```

1. The human usage of svn is different than git
- In git, repos are cheap for the server, and easy for human users to create, self-service, so humans usually create a new git repo for each company product or project
- In svn, only the server administrators can create new repos, so most companies only have one repo per svn server, or one repo per division of the company's org chart, so each division's products / projects are usually rooted in top-level or second-level directory of the repo. Perforce is also quite similar this way.

2. The svn revision number index is shared across the entire repo, therefore different products / projects / top-level folders may only be relevant at different ranges of the revision index.
- If a product was built and completed early in the svn repo's history and left dormant, then only ranges of lower revision numbers would be relevant for efficient batch processing, even though this project may have maintenance commits later in the svn repo's history.
- If multiple separate projects are both in active development at the same time, that range of revision numbers may go back and forth between those projects.

3. This repo-converter system is designed to adapt repo organization to match the differences in human usage from svn to git, i.e. break up a large svn repo into smaller git repos.
- From the perspectives of conversion system stability and performance: each repo conversion job execution only needs to handle a subset of revision numbers.

4. svn (and thus, the `git svn` command in git) is largely abandoned, so many of the quality of life features which have been added to git over the years are missing in svn
- svn does not have rate limiting built in, so there's no HTTP 429 response, or `Retry-After` header
- `git svn fetch` does not have robust error handling, retries, or batch processing features, so many features need to be built into the repo-converter system to make up for these shortcomings
- If batch processing logic is required, such as allowing the user to specify a number of commits in the `fetch-batch-size` config, it must find a way to make use of a subset of revisions specifically relevant to code changes under the targeted directory.
- The `--log-window-size n` arg to the `git svn fetch` command is only used to request `n` revision numbers from the svn repo's index of revision numbers, per network request, which may or may not have any commits to the subdirectory the job is trying to convert
    - However, this may still be useful for svn repos / subdirectories which seem to have performance issues, so we should implement a retry / backoff method
    - The default `--log-window-size` is 100, so if a request times out, we should cut this value in half and retry
    - For customer svn repo revision indexes with millions of revisions, smaller window sizes result in many, many network requests to the svn server
    - Request timeouts happen more often in conversion jobs when:
        - The `--log-window-size` is too large, and the request times out / gets dropped at after 10 minutes of processing time
        - The `--log-window-size` is too small, which multiplies the number of requests required to convert the repo, and every new request has its own possibility of timing out

5. The `_calculate_batch_revisions`, then `_git_svn_fetch` functions are only ever called after the `_check_if_repo_already_up_to_date` function concludes that the local git repo is behind the remote svn server, based on the "Last Changed Rev" response to the `svn info` command above
- Therefore, any `git svn fetch` execution which doesn't return any lines of output is considered a failure, even if the return_code is 0
- Therefore, we cannot trust the return code as an indicator of task success
- We must determine task success based on data in the local git repo, and the lines in stdout from the `git svn fetch` command
