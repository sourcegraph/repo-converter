#!/bin/bash

# Bash script to print, in a CSV table format
# the disk usage, and the most recently modified file, in each child directory of the given directory

# Args:
# 1. The directory to scan
# 2. The number of lines to reprint the header
# 3. The number of seconds to wait between scans
# 4. The CSV output file

# Example:
# ./dir-stats.sh /path/to/dir 10 10 /path/to/output.csv

# If a directory is provided, use it, otherwise use the current directory
if [ -z "$1" ]; then
    dir="."
else
    dir="$1"
fi

# Check if the directory exists and is readable
if [ ! -d "$dir" ] || [ ! -r "$dir" ]; then
    echo "Error: Directory $dir does not exist or is not readable"
    exit 1
fi

# Set how often to reprint the header
# If a second arg is provided, use it as the print header every n lines
if [ -n "$2" ]; then
    print_header_every_n_lines="$2"
else
    print_header_every_n_lines=10
fi

# Set the number of seconds to wait between scans
# If a third arg is provided, use it as the number of seconds to wait between scans
if [ -n "$3" ]; then
    sleep_seconds="$3"
else
    sleep_seconds=10
fi

# Set the CSV output file
if [ -n "$4" ]; then
    csv_output_file="$4"
else
    csv_output_file="dir-stats.csv"
fi

# Define the CSV header line
header_line="Date, Time, Repo, Last Modified Date, Last Modified Time, Seconds since last modified, Size (bytes), Size (human readable)"

# Print the header line, to both the console, and append to the output file
echo "$header_line"
echo "$header_line" >> "$csv_output_file"

lines_since_header_printed=0

# Loop until the user quits
while true; do

    # Increment the current line count
    lines_since_header_printed=$((lines_since_header_printed + 1))

    # If the current line count is equal to the print header ever n lines
    if [ $lines_since_header_printed -eq $print_header_every_n_lines ]; then
        # Print the header line
        echo "$header_line"
        echo "$header_line" >> "$csv_output_file"
        # Reset the line count
        lines_since_header_printed=0
    fi

    # Get the list of child directories
    child_dirs=$(find "$dir" -maxdepth 1 -type d)

    # Get the length of the longest child directory name
    longest_child_dir_name_length=$(echo "$child_dirs" | awk '{print length($0)}' | sort -nr | head -1)

    # Loop through the list of child directories
    for child_dir in $child_dirs; do

        # Get the current date
        date=$(date +%Y-%m-%d)
        # Get the current time
        time=$(date +%H:%M:%S)

        # Get the repo name, and pad it with spaces to the longest child directory name length
        repo=$(basename "$child_dir")
        repo=$(printf "%-${longest_child_dir_name_length}s" "$repo")

        # Get the date and time of the most recently modified file in the child directory
        # Format: %Y-%m-%d %H:%M:%S
        most_recent_file=$(find "$child_dir" -type f -printf '%T@ %p\n' | sort -n | tail -1 | awk '{print $2}')

        # Get the date and time of the most recently modified file
        most_recent_file_modified_date=$(date -r "$most_recent_file" +%Y-%m-%d)
        most_recent_file_modified_time=$(date -r "$most_recent_file" +%H:%M:%S)

        # Get the seconds since the most recently modified file
        seconds_since_last_modified=$(date -r "$most_recent_file" +%s)

        # Get the total disk usage of the child directory, in bytes
        disk_usage_bytes=$(du -sb "$child_dir" | awk '{print $1}')

        # Get the total disk usage of the child directory, in human readable format
        disk_usage_human=$(du -sh "$child_dir" | awk '{print $1}')

        # Print the child directory, disk usage, and most recent file
        # to the console, and append to the output file
        line="$date, $time, $repo, $most_recent_file_modified_date, $most_recent_file_modified_time, $seconds_since_last_modified, $disk_usage_bytes, $disk_usage_human"
        echo "$line"
        echo "$line" >> "$csv_output_file"

    done

done
