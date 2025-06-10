#!/usr/bin/env python3
# Main application logic to
# iterate through the repos_to_convert_dict,
# and spawn sub processes,
# based on parallelism limits per server

# Import repo-converter modules
from utils.context import Context
from utils.logger import log
from source_repo import svn

# Import Python standard modules
import multiprocessing


def start(ctx: Context) -> None:

    # TODO: Enforce parallelism limits, total, and per server

    # Loop through the repos_dict
    for repo_key in ctx.repos.keys():

        # Check if we're already at the total parallelism limit

        # Find server

        # Check if the server is already at its parallelism limit

        # Find the repo type
        repo_type = ctx.repos[repo_key].get("type","").lower()

        # Fork off a process to clone the repo
        if repo_type in ("svn", "subversion"):

            log(ctx, f"Starting repo type {repo_type}, name {repo_key}")
            multiprocessing.Process(target=svn.clone_svn_repo, name=f"clone_svn_repo_{repo_key}", args=(ctx, repo_key)).start()
