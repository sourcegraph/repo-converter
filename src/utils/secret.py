#!/usr/bin/env python3
# Secrets handling

# Import repo-converter modules
from utils.context import Context


def add(ctx: Context, secret) -> None:
    """Add a secret to the set of secrets, as a string"""

    ctx.secrets.add(str(secret))


def redact(ctx: Context, input):
    """Redact secrets from an input."""

    # Handle different types
    # Return the same type this function was given
    # If input is a dict or list, uses recursion to depth-first-search through the values, with arbitrary depths, keys, and value types

    secrets_set = ctx.secrets

    # If the message is None, or the secrets_set is empty, or none of the secrets in the secrets set are in the input, then just return the input as is
    if (
        isinstance(input, type(None)) or
        isinstance(input, type(bool)) or
        len(secrets_set) == 0 or
        not any(secret in str(input) for secret in secrets_set)
    ):

        return input

    # If it's type string, just use string's built-in .replace()
    elif isinstance(input, str):

        for secret in secrets_set:
            if secret in input:
                redacted_input = input.replace(secret, "REDACTED_SECRET")

    # If it's type int, cast it to a string, then recurse this function again to use string's built-in .replace()
    elif isinstance(input, int):

        # Can't add the redacted message to an int, so just remove it
        redacted_input_string = str(input).replace(secret, "")

        # Cast back to an int to return the same type
        redacted_input = int(redacted_input_string)

    # AttributeError: 'list' object has no attribute 'replace'
    # Need to iterate through the items in the list
    elif isinstance(input, list):

        redacted_input = []
        for item in input:

            # TODO: Chances are, most lines in the list do not contain a secret
            # Would it be more efficient to check for the presence of a secret before sending the line back through this function?

            # Send the list item back through this function to hit any of the non-list types
            redacted_input.append(redact(ctx, item))

    # If it's a dict, recurse through the dict, until it gets down to primitive types
    elif isinstance(input, dict):

        redacted_input = {}

        for key in input.keys():

            # Check if the secret is in the key, and convert it to a string
            key_string = redact(ctx, str(key))

            # Send the value back through this function to hit any of the non-list types
            redacted_input[key_string] = redact(ctx, input[key])

    else:

        # Set it to None to just break the code instead of leak the secret
        redacted_input = None

        # Use an exception instead of importing the logging module and creating a circular import
        raise Exception(f"redact() doesn't handle input of type {type(input)}")

    return redacted_input
