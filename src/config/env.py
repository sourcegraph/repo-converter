#!/usr/bin/env python3
# Environment variable handling

# Import Python standard modules
from os import environ

# Import third party modules
from dotenv import load_dotenv # https://pypi.org/project/python-dotenv/


def load_env_vars():
    """Load config from environment variables"""

    # Read the contents of ./.env into env vars
    load_dotenv()

    env_vars = {}

    # Try to read the variables from the Docker container's environment
    # Set defaults in case they're not defined

    # DEBUG INFO WARNING ERROR CRITICAL
    env_vars["LOG_LEVEL"]                               = str(environ.get("LOG_LEVEL"                               , "INFO" ))
    env_vars["MAX_CONCURRENT_CONVERSIONS_TOTAL"]        = int(environ.get("MAX_CONCURRENT_CONVERSIONS_TOTAL"        , 10     ))
    env_vars["MAX_CONCURRENT_CONVERSIONS_PER_SERVER"]   = int(environ.get("MAX_CONCURRENT_CONVERSIONS_PER_SERVER"   , 10     ))
    env_vars["MAX_CYCLES"]                              = int(environ.get("MAX_CYCLES"                              , ""     ))
    env_vars["REPO_CONVERTER_INTERVAL_SECONDS"]         = int(environ.get("REPO_CONVERTER_INTERVAL_SECONDS"         , 3600   ))
    # Path inside the container to find this file, only change to match if the right side of the volume mapping changes
    env_vars["REPOS_TO_CONVERT"]                        = str(environ.get("REPOS_TO_CONVERT"                        , "/sourcegraph/repos-to-convert.yaml" ))
    # Path inside the container to find this directory, only change to match if the right side of the volume mapping changes
    env_vars["SRC_SERVE_ROOT"]                          = str(environ.get("SRC_SERVE_ROOT"                          , "/sourcegraph/src-serve-root" ))

    # Image build info
    env_vars["BUILD_BRANCH"]                            = str(environ.get("BUILD_BRANCH"                            , "" ))
    env_vars["BUILD_COMMIT"]                            = str(environ.get("BUILD_COMMIT"                            , "" ))
    env_vars["BUILD_DATE"]                              = str(environ.get("BUILD_DATE"                              , "" ))
    env_vars["BUILD_DIRTY"]                             = str(environ.get("BUILD_DIRTY"                             , "" ))
    env_vars["BUILD_TAG"]                               = str(environ.get("BUILD_TAG"                               , "" ))


# def load_config_from_repos_to_convert_file():
#     # Try to load the environment variables from the REPOS_TO_CONVERT file


#     # Check if the default config file exists
#     # If yes, read configs from it
#     # If no, use the environment variables
#     pass

    return env_vars
