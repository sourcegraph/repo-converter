#!/usr/bin/env python3
"""
Parse JSON structured logs and output CSV based on process execution data.

This script filters log entries where process.execution_time_seconds is a number
and extracts specific fields to CSV format, equivalent to the provided jq query.

This script was entirely written by Amp, without human review of the code, but the output CSV file seems fine

Usage:

```bash
python dev/query_logs.py logs/2025-07-11-07-27-05-customer.json && cat logs/2025-07-11-07-27-05-customer.csv | pbcopy
```

Then paste into a Google Sheet, and create pivot tables as needed
"""

import argparse
import csv
import json
import re
import sys
from typing import Any, Dict, List, Optional


def safe_get(data: Dict[str, Any], path: str) -> Optional[Any]:
    """
    Safely get a nested value from a dictionary using dot notation.

    Args:
        data: The dictionary to search
        path: Dot-separated path (e.g., "process.execution_time_seconds")

    Returns:
        The value at the path, or None if not found
    """
    keys = path.split('.')
    current = data

    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None

    return current


def should_include_record(record: Dict[str, Any]) -> bool:
    """
    Check if record should be included based on jq filter criteria.

    Args:
        record: JSON log record

    Returns:
        True if job.result.execution_time is a number, False otherwise
    """
    execution_time = safe_get(record, 'job.result.execution_time')
    return isinstance(execution_time, (int, float))


def extract_limit_from_args(args_str: str) -> str:
    """
    Extract the limit value from process args if --limit <integer> is present.

    Args:
        args_str: The process args string

    Returns:
        The limit value as string, or empty string if not found
    """
    if not args_str:
        return ''

    # Look for --limit followed by an integer
    match = re.search(r'--limit\s+(\d+)', args_str)
    if match:
        return match.group(1)

    return ''


def extract_revision_range_from_args(args_str: str) -> tuple[str, str]:
    """
    Extract the revision range values from process args if --revision is present.

    Args:
        args_str: The process args string

    Returns:
        Tuple of (start_rev, end_rev) as strings, or ('', '') if not found
    """
    if not args_str:
        return ('', '')

    # Look for --revision followed by a range (formats like "1:100", "abc:def", "HEAD:1234", etc.)
    # Match alphanumeric characters, dots, underscores, and hyphens for revision identifiers
    match = re.search(r'--revision\s+([a-zA-Z0-9._-]+)[:,-]([a-zA-Z0-9._-]+)', args_str)
    if match:
        return (match.group(1), match.group(2))

    return ('', '')


def extract_command_from_args(args_str: str) -> str:
    """
    Extract the command and subcommand from process args.

    Args:
        args_str: The process args string

    Returns:
        The command and subcommand as a string, or empty string if not found
    """
    if not args_str:
        return ''

    # Split into tokens
    tokens = args_str.split()
    if not tokens:
        return ''

    command_parts = []
    i = 0

    # First token is always the main command (git, svn, etc.)
    command_parts.append(tokens[i])
    i += 1

    # Process remaining tokens
    while i < len(tokens):
        token = tokens[i]

        # Skip -C and its path argument
        if token == '-C' and i + 1 < len(tokens):
            i += 2  # Skip -C and the path
            continue

        # Stop at options (starting with -), URLs, HEAD, or paths that look like parameters
        if (token.startswith('-') or
            token.startswith('http') or
            token == 'HEAD' or
            token.startswith('refs/') or
            '/' in token and len(token) > 10):  # Likely a path
            break

        # This is likely a subcommand
        command_parts.append(token)
        i += 1

    return ' '.join(command_parts)


def extract_fields(record: Dict[str, Any]) -> List[str]:
    """
    Extract fields from record in the order specified by the jq query.

    Args:
        record: JSON log record

    Returns:
        List of field values as strings
    """
    # Field mapping with new order: timestamp, cycle, command, then other fields
    fields = [
        'timestamp',
        'cycle',
        'job.config.repo_key',
        'process.execution_time_seconds',
        'process.output_line_count',
        'process.success',
        'process.return_code',
        'level',
        'process.args',
        'process.name',
        'date',
        'time',
        'process.span',
        'job.trace'
    ]

    # Extract values and convert to strings
    row = []

    # Get process_args for parsing command, limit and revision
    process_args = safe_get(record, 'process.args')
    process_args = str(process_args) if process_args else ''

    # Extract command value for later use
    command_value = extract_command_from_args(process_args)

    # Extract limit, start_rev, end_rev for later use
    limit_value = extract_limit_from_args(process_args)
    start_rev, end_rev = extract_revision_range_from_args(process_args)

    # Process all fields in order, inserting special columns at appropriate positions
    for i, field in enumerate(fields):
        if field == 'timestamp':
            timestamp = safe_get(record, field)
            row.append(str(timestamp) if timestamp else '')
        elif field == 'cycle':
            cycle = safe_get(record, field)
            row.append(str(cycle) if cycle else '')
            # After cycle, add command
            row.append(command_value)
            # Add new job result and stats columns
            job_action = safe_get(record, 'job.result.action')
            row.append(str(job_action) if job_action else '')
            job_success = safe_get(record, 'job.result.success')
            row.append(str(job_success) if job_success is not None else '')
            job_reason = safe_get(record, 'job.result.reason')
            row.append(str(job_reason) if job_reason else '')
            job_execution_time = safe_get(record, 'job.result.execution_time')
            row.append(str(job_execution_time) if job_execution_time else '')
            batch_count = safe_get(record, 'job.stats.local.fetching_batch_count')
            row.append(str(batch_count) if batch_count else '')
            commits_added = safe_get(record, 'job.stats.local.git_commits_added')
            row.append(str(commits_added) if commits_added else '')
            commit_count_start = safe_get(record, 'job.stats.local.git_repo_commit_count_start')
            row.append(str(commit_count_start) if commit_count_start else '')
            commit_count_end = safe_get(record, 'job.stats.local.git_repo_commit_count_end')
            row.append(str(commit_count_end) if commit_count_end else '')
            latest_rev_start = safe_get(record, 'job.stats.local.git_repo_latest_converted_svn_rev_start')
            row.append(str(latest_rev_start) if latest_rev_start else '')
            latest_rev_end = safe_get(record, 'job.stats.local.git_repo_latest_converted_svn_rev_end')
            row.append(str(latest_rev_end) if latest_rev_end else '')
            batch_start_rev = safe_get(record, 'job.stats.local.this_batch_start_rev')
            row.append(str(batch_start_rev) if batch_start_rev else '')
            batch_end_rev = safe_get(record, 'job.stats.local.this_batch_end_rev')
            row.append(str(batch_end_rev) if batch_end_rev else '')
        elif field == 'process.name':
            # After process.name, add limit, start_rev, end_rev
            process_name = safe_get(record, field)
            row.append(str(process_name) if process_name else '')
            row.append(limit_value)
            row.append(start_rev)
            row.append(end_rev)
        elif field == 'process.execution_time_seconds':
            # Convert to integer
            value = safe_get(record, field)
            if value is not None:
                row.append(str(int(float(value))))
            else:
                row.append('')
        else:
            # Regular field extraction
            value = safe_get(record, field)
            row.append(str(value) if value is not None else '')

    return row


def parse_logs_to_csv(input_file: str, output_file: str) -> None:
    """
    Parse JSON logs file and write matching records to CSV.

    Args:
        input_file: Path to input JSON logs file
        output_file: Path to output CSV file
    """
    # CSV headers with new order: timestamp, cycle, command, then other fields
    headers = [
        'Timestamp',
        'Cycle',
        'Command',
        'Job Action',
        'Job Success',
        'Job Reason',
        'Job Execution Time',
        'Batch Count',
        'Commits Added',
        'Commit Count Start',
        'Commit Count End',
        'Latest Rev at Start',
        'Latest Rev at End',
        'Batch Start Rev',
        'Batch End Rev',
        'Repo Key',
        'Execution Time Seconds',
        'Output Line Count',
        'Success',
        'Return Code',
        'Level',
        'Process Args',
        'Process Name',
        'Limit',
        'Start Rev',
        'End Rev',
        'Date',
        'Time',
        'Process Id',
        'Job Id'
    ]

    try:
        with open(input_file, 'r') as infile, open(output_file, 'w', newline='') as outfile:
            csv_writer = csv.writer(outfile)
            # Write header row
            csv_writer.writerow(headers)

            # Read entire file and try to parse as concatenated JSON objects
            content = infile.read()

            # Split on lines and try to parse, but also handle multi-line JSON
            current_json = ""
            brace_count = 0
            line_num = 0

            for line in content.split('\n'):
                line_num += 1
                line = line.strip()

                if not line:
                    continue

                current_json += line + " "

                # Count braces to detect complete JSON objects
                brace_count += line.count('{') - line.count('}')

                # When braces are balanced, we might have a complete JSON object
                if brace_count == 0 and current_json.strip():
                    try:
                        # Parse JSON record
                        record = json.loads(current_json.strip())

                        # Check if record matches filter criteria
                        if should_include_record(record):
                            # Extract fields and write to CSV
                            row = extract_fields(record)
                            csv_writer.writerow(row)

                        # Reset for next JSON object
                        current_json = ""

                    except json.JSONDecodeError as e:
                        # If single line fails, try just this line (for single-line JSON)
                        try:
                            record = json.loads(line)
                            if should_include_record(record):
                                row = extract_fields(record)
                                csv_writer.writerow(row)
                            current_json = ""
                        except json.JSONDecodeError:
                            print(f"Warning: Invalid JSON around line {line_num}: {e}", file=sys.stderr)
                            current_json = ""
                            brace_count = 0
                    except Exception as e:
                        print(f"Warning: Error processing JSON around line {line_num}: {e}", file=sys.stderr)
                        current_json = ""
                        brace_count = 0

    except FileNotFoundError:
        print(f"Error: Input file '{input_file}' not found", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description='Parse JSON structured logs and output CSV with process execution data'
    )
    parser.add_argument(
        'input_file',
        help='Path to JSON logs file to parse'
    )
    parser.add_argument(
        '-o', '--output',
        default=None,
        help='Output CSV file (defaults to input_file.csv)'
    )

    args = parser.parse_args()

    # Generate output filename if not provided
    if args.output is None:
        if args.input_file.endswith('.json'):
            output_file = args.input_file[:-5] + '.csv'
        else:
            output_file = args.input_file + '.csv'
    else:
        output_file = args.output

    # Parse logs and generate CSV
    parse_logs_to_csv(args.input_file, output_file)
    print(f"CSV output written to: {output_file}")


if __name__ == '__main__':
    main()
