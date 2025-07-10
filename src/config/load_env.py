#!/usr/bin/env python3
# Load Environment variables into context

# Import repo-converter modules
# context and logging are not available, as it would create a circular import
# Loading and validating environment variables are separate modules, because validation uses context and logging

# Import Python standard modules
from os import environ

# Import third party modules
from dotenv import load_dotenv # https://pypi.org/project/python-dotenv/


def load_env_vars() -> dict:
    """Load config from environment variables"""

    # Read the contents of the .env file into env vars
    # The only use of this .env file is to bake env vars into container image during build,
    # so it's fine to hard code the path in his file, as long as the file path in the build matches
    # Do not overwrite any existing env vars with the same name (default behaviour),
    # so that env vars provided at container start time take precedence
    dotenv_path="/sourcegraph/repo-converter/build/.env"
    load_dotenv(dotenv_path=dotenv_path, override=False)

    # Create empty env_vars dict to return at function exit
    env_vars = {}

    # Try to read the variables from the container's environment
    # Set defaults in case they're not defined, where appropriate
    # Handle type casting here, instead of throughout the code

    # Build metadata
    env_vars["BUILD_BRANCH"]                            = str(environ.get("BUILD_BRANCH"                            , "" ))
    env_vars["BUILD_COMMIT"]                            = str(environ.get("BUILD_COMMIT"                            , "" ))
    env_vars["BUILD_COMMIT_MESSAGE"]                    = str(environ.get("BUILD_COMMIT_MESSAGE"                    , "" ))
    env_vars["BUILD_DATE"]                              = str(environ.get("BUILD_DATE"                              , "" ))
    env_vars["BUILD_DIRTY"]                             = str(environ.get("BUILD_DIRTY"                             , "" ))
    env_vars["BUILD_TAG"]                               = str(environ.get("BUILD_TAG"                               , "" ))
    env_vars["CONCURRENCY_MONITOR_INTERVAL"]            = int(environ.get("CONCURRENCY_MONITOR_INTERVAL"            , 60 ))
    env_vars["CREDENTIALS"]                             = str(environ.get("CREDENTIALS"                             , "" ))
    # DEBUG INFO WARNING ERROR CRITICAL
    env_vars["LOG_LEVEL"]                               = str(environ.get("LOG_LEVEL"                               , "INFO" ))
    env_vars["LOG_RECENT_COMMITS"]                      = int(environ.get("LOG_RECENT_COMMITS"                      , 0  ))
    env_vars["MAX_CONCURRENT_CONVERSIONS_PER_SERVER"]   = int(environ.get("MAX_CONCURRENT_CONVERSIONS_PER_SERVER"   , 10 ))
    env_vars["MAX_CONCURRENT_CONVERSIONS_GLOBAL"]       = int(environ.get("MAX_CONCURRENT_CONVERSIONS_GLOBAL"       , 10 ))
    # Max cycles of the main loop, then the container exits
    env_vars["MAX_CYCLES"]                              = int(environ.get("MAX_CYCLES"                              , 0 ))
    env_vars["MAX_RETRIES"]                             = int(environ.get("MAX_RETRIES"                             , 3 ))
    env_vars["REPO_CONVERTER_INTERVAL_SECONDS"]         = int(environ.get("REPO_CONVERTER_INTERVAL_SECONDS"         , 3600 ))
    # Paths inside the container, don't change unless also changing in compose file volume mapping
    env_vars["REPOS_TO_CONVERT"]                        = str(environ.get("REPOS_TO_CONVERT"                        , "/sourcegraph/repos-to-convert.yaml" ))
    env_vars["SRC_SERVE_ROOT"]                          = str(environ.get("SRC_SERVE_ROOT"                          , "/sourcegraph/src-serve-root" ))
    env_vars["TRUNCATED_OUTPUT_MAX_LINE_LENGTH"]        = int(environ.get("TRUNCATED_OUTPUT_MAX_LINE_LENGTH"        , 200 ))
    env_vars["TRUNCATED_OUTPUT_MAX_LINES"]              = int(environ.get("TRUNCATED_OUTPUT_MAX_LINES"              , 11 ))

    # String to use in log events
    # Prefer the tag if available
    # Otherwise use the commit short hash
    build_tag_or_commit_for_logs = ""
    if env_vars["BUILD_TAG"]:
        build_tag_or_commit_for_logs = env_vars["BUILD_TAG"]
    elif env_vars["BUILD_COMMIT"]:
        build_tag_or_commit_for_logs = env_vars["BUILD_COMMIT"]
    env_vars["BUILD_TAG_OR_COMMIT_FOR_LOGS"] = build_tag_or_commit_for_logs


    # TODO: Try to load the environment variables from the REPOS_TO_CONVERT file
    # Check if the default config file exists
    # If yes, read configs from it
    # If no, use the environment variables

    return env_vars
