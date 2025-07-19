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
    print_header_every_n_cycles="$2"
else
    print_header_every_n_cycles=100
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

cycles_since_header_printed=$print_header_every_n_cycles

# Loop until the user quits
while true; do

    # Get the list of child directories
    child_dirs=$(find "$dir" -maxdepth 1 -type d | sort)

    # Ensure the list of directories has the current directory at the beginning
    child_dirs=$(echo "$child_dirs" | sed '1d')
    child_dirs="$dir $child_dirs"

    # Get the length of the longest child directory name's basename
    longest_child_dir_name_length=0
    for child_dir in $child_dirs; do
        name=$(basename "$child_dir")
        len=${#name}
        if [ "$len" -gt "$longest_child_dir_name_length" ]; then
            longest_child_dir_name_length=$len
        fi
    done

    # If the current line count is equal to the print header ever n lines
    if [ "$cycles_since_header_printed" -eq "$print_header_every_n_cycles" ]; then

        repo_column_name="Repo"
        repo_column_name_length=$(echo "$repo_column_name" | wc -c)
        repo_column_name_padding_length=$((longest_child_dir_name_length - repo_column_name_length + 2))
        repo_column_name_padding=$(printf "%${repo_column_name_padding_length}s" " ")
        repo_column_name_string="$repo_column_name$repo_column_name_padding"

        seconds_since_mod_date_column_name="Seconds since mod"
        seconds_since_mod_date_column_name_length=$(echo "$seconds_since_mod_date_column_name" | wc -c)

        # Define the CSV header line
        header_line="Date,       Time,     $repo_column_name_string,  Mod Date,   Mod Time, $seconds_since_mod_date_column_name, Size (bytes), Size (human readable)"

        # Print the header line
        echo "$header_line"
        echo "$header_line" >> "$csv_output_file"
        # Reset the line count
        cycles_since_header_printed=0
    fi

    # Increment the current line count
    cycles_since_header_printed=$((cycles_since_header_printed + 1))

    # Loop through the list of child directories
    for child_dir in $child_dirs; do

        # Get the current date
        date=$(date +%Y-%m-%d)
        # Get the current time
        time=$(date +%H:%M:%S)
        current_time_seconds=$(date +%s)

        # Get the repo name, and pad it with spaces to the longest child directory name length
        repo_column_name=$(basename "$child_dir")
        repo_column_name_length=$(echo "$repo_column_name" | wc -c)
        repo_column_name_padding_length=$((longest_child_dir_name_length - repo_column_name_length + 2))
        repo_column_name_padding=$(printf "%${repo_column_name_padding_length}s" " ")
        repo_column_name_string="$repo_column_name$repo_column_name_padding"

        # Get the date and time of the most recently modified file in the child directory
        # Format: %Y-%m-%d %H:%M:%S
        # Send stderr from find to /dev/null
        most_recent_file=$(find "$child_dir" -type f -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | awk '{print $2}')

        # Get the date and time of the most recently modified file
        # Send stderr from date to /dev/null
        most_recent_file_modified_date=$(date -r "$most_recent_file" +%Y-%m-%d 2>/dev/null)
        # If most_recent_file_modified_date is empty, then set it to a string of spaces, of length 10
        if [ -z "$most_recent_file_modified_date" ]; then
            most_recent_file_modified_date=$(printf "%10s" " ") # 10 spaces
        fi

        # Get the time of the most recently modified file
        most_recent_file_modified_time=$(date -r "$most_recent_file" +%H:%M:%S 2>/dev/null)
        # If most_recent_file_modified_time is empty, then set it to a string of spaces, of length 8
        if [ -z "$most_recent_file_modified_time" ]; then
            most_recent_file_modified_time=$(printf "%8s" " ") # 8 spaces
        fi

        # Get the seconds since the most recently modified file
        # Send stderr from date to /dev/null
        most_recent_file_modified_time_seconds=$(date -r "$most_recent_file" +%s 2>/dev/null)

        seconds_since_last_modified=""

        # If most_recent_file_modified_time_seconds is empty, then set it to a string of spaces, of length 10
        if [ -z "$most_recent_file_modified_time_seconds" ]; then
            most_recent_file_modified_time_seconds=$(printf "%10s" " ") # 10 spaces
        else
            seconds_since_last_modified=$((current_time_seconds - most_recent_file_modified_time_seconds))
        fi

        # Add a string of padding spaces, to make the seconds since last modified column the same length as the seconds since last modified column in the header
        seconds_since_last_modified_length=$(echo "$seconds_since_last_modified" | wc -c)
        seconds_since_last_modified_padding_length=$((seconds_since_mod_date_column_name_length - seconds_since_last_modified_length))
        seconds_since_last_modified_padding=$(printf "%${seconds_since_last_modified_padding_length}s" " ")
        seconds_since_last_modified_string="$seconds_since_last_modified$seconds_since_last_modified_padding"

        # Get the total disk usage of the child directory, in bytes
        # Send stderr from du to /dev/null
        disk_usage_bytes=$(du -sb "$child_dir" 2>/dev/null | awk '{print $1}')
        # Add padding to the disk usage bytes, to make it length 12
        disk_usage_bytes_length=$(echo "$disk_usage_bytes" | wc -c)
        disk_usage_bytes_padding_length=$((12 - disk_usage_bytes_length))
        disk_usage_bytes_padding=$(printf "%${disk_usage_bytes_padding_length}s" " ")
        disk_usage_bytes_string="$disk_usage_bytes$disk_usage_bytes_padding"

        # Get the total disk usage of the child directory, in human readable format
        # Send stderr from du to /dev/null
        disk_usage_human=$(du -sh "$child_dir" 2>/dev/null | awk '{print $1}')

        # Print the child directory, disk usage, and most recent file
        # to the console, and append to the output file
        # Add spaces to the repo name to make it the same length as the longest child directory name
        line="$date, $time, $repo_column_name_string, $most_recent_file_modified_date, $most_recent_file_modified_time, $seconds_since_last_modified_string, $disk_usage_bytes_string, $disk_usage_human"
        echo "$line"
        echo "$line" >> "$csv_output_file"

    done

    # Wait for the specified number of seconds
    sleep "$sleep_seconds"

done
