#!/usr/bin/env python3
# TFVC repository handling

# from .base import Repo

# class TFVCRepo(Repo):
#     """Class for TFVC repository operations."""

#     def __init__(self):
#         super().__init__()

#     def clone(self):
#         """Clone a TFVC repository."""
#         raise NotImplementedError("TFVC clone not implemented yet")

#     def update(self):
#         """Update a TFVC repository."""
#         raise NotImplementedError("TFVC update not implemented yet")


# Import repo-converter modules
from utils.context import Context
from utils.logger import log


def clone_tfs_repos(ctx: Context) -> None:

    log(ctx, "Cloning TFS repos function not implemented yet", "warning")

    # # Declare an empty dict for TFS repos to extract them from the repos_dict
    # tfs_repos_dict = {}

    # # Loop through the repos_dict, find the type: tfs repos, then add them to the dict of TFS repos
    # for repo_key in repos_dict.keys():

    #     repo_type = repos_dict[repo_key].get('type','').lower()

    #     if repo_type == 'tfs' or repo_type == 'tfvc':

    #         tfs_repos_dict[repo_key] = repos_dict[repo_key]


    # log(ctx, f"Cloning TFS repos: {str(tfs_repos_dict)}", "info")
