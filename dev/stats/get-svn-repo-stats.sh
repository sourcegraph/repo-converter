#!/bin/bash

## TODO:
    # Add count of authors

# Get username from first parameter
username=$1

# Get password from second parameter
password=$2

# Input text file with a list of repos to process
# One repo per line, with an empty line at the end
svn_stats_repos_file="repos.txt"

# Output CSV file path/name
svn_stats_csv_file="${0##*/}.csv"

# Metadata folder
tmp_metadata_folder="./tmp-repo-metadata"
repo_name_prefix_to_remove=$3

# Starting count for this execution
starting_array_index=0


# List of repos to get commit counts from
# # Comment out any repos from the list to skip
declare -a repos

# If the input text CSV file already exists, then try and get the number of the last repo that was logged
if test -f "$svn_stats_repos_file"
then

    readarray -t repos < "$svn_stats_repos_file"

else

    exit 1

fi

# If the output CSV file already exists, then try and get the number of the last repo that was logged
if test -f "$svn_stats_csv_file"
then

    svn_stats_csv_file_total_lines=$(wc -l "$svn_stats_csv_file" | awk '{print $1}')
    # echo "$svn_stats_csv_file exists with $svn_stats_csv_file_total_lines lines"

    last_repo_number=""
    number_regex='^[0-9]+$'

    # Iterate backwards through the file until a number is found in the first item of a line
    for (( i=0; i<svn_stats_csv_file_total_lines; i++))
    do

        # Get the last nth line of the file, and grab the first CSV column from it
        last_line_text=$( tail -n "$i" "$svn_stats_csv_file" | head -n 1 )
        # echo "last_line_text is $last_line_text"

        last_repo_number=$( echo "$last_line_text" | awk -F, '{print $1}' )
        # echo "last_repo_number is $last_repo_number"

        # If we got a number, exit the loop
        if [[ $last_repo_number =~ $number_regex ]]
        then

            break

        fi

    done

    # If we got a number in the end, then use it as the starting index array for this iteration
    if [[ $last_repo_number =~ $number_regex ]]
    then

        echo "$svn_stats_csv_file has last repo number $last_repo_number"
        starting_array_index=$((last_repo_number))

        # If the last repo number is greater than or equal to the number of repos in the array, then exit the script
        if [[ $last_repo_number -ge ${#repos[@]} ]]
        then

            echo "$svn_stats_csv_file has last repo number $last_repo_number, which is greater than or equal to the number of repos in the input file, exiting the script."

        fi

    else

        echo "$svn_stats_csv_file exists but couldn't find a repo number in the first column of any line, starting from $starting_array_index"

    fi

fi

# Output the CSV header
csv_header="Index,Date,Time,Repo,Revs,Newest Rev,Oldest Rev,Revs in the Last Month,Revs in the Last Year,Download Time,Download Revs per Second"
output_string="$repo_index,$date_string,$time_string,$repo,$revisions_count,$newest_commit_date,$oldest_commit_date,$revisions_in_last_month,$revisions_in_last_year,$download_time,$download_revs_per_sec"

echo "$csv_header" >> "$svn_stats_csv_file"
echo "$csv_header"

mkdir -p "$tmp_metadata_folder"

# Loop through the list of repos above
for (( i=starting_array_index; i<${#repos[@]}; i++))
do

    # Get the repo name
    repo=${repos[$i]}

    # Remove the prefix
    repo_short_name=${repo#"$repo_name_prefix_to_remove"}

    # Replace all instances of / in the remaining path with -
    repo_short_name=${repo_short_name//\//-}

    # Create the repo log file name string
    repo_log_file="$tmp_metadata_folder/$repo_short_name.xml"

    # Output to the console to show which repo we're trying to get to the anxious operator
    date_string=$(date +%Y-%m-%d)
    time_string=$(date +%H:%M:%S)
    repo_index=$((i+1))
    output_string="$repo_index,$date_string,$time_string,$repo"
    echo "$output_string"

    # Start the timer
    download_start_time=$(date +%s)

    # Get the repo's commit log, write to both the console and the output file
    svn log --xml "$repo" --username "$username" --password "$password" 2>&1 | tee "$repo_log_file"

    # Calculate the time it took to get the repo's log
    download_time=$(($(date +%s) - download_start_time))

    # Extract the oldest and newest commit dates
    # The log is sorted in reverse chronological order, with the latest commit on top
    # Date format: <date>2012-10-10T15:51:44.227958Z</date>
    svn_log_date_regex="<date>([0-9-]+)[T0-9:\.Z]+<\/date>"
    revision_dates=$(sed -nr "s/$svn_log_date_regex/\1/p" "$repo_log_file")
    revisions_count=$(echo "$revision_dates" | wc -l | tr -d '[:space:]')
    newest_commit_date=$(echo "$revision_dates" | head -n 1)
    oldest_commit_date=$(echo "$revision_dates" | tail -n 1)

    # Calculate the rate of revisions per second over the network
    download_revs_per_sec=$(echo "$revisions_count/$download_time" | bc)

    # Get the dates from 1 year ago and 30 days ago
    # If the date command doesn't support the -v option, then use the date command without the -v option
    if ! date -v -30d +%Y-%m-%d > /dev/null 2>&1
    then

        date_one_month_ago=$(date --date='-1 month' +%Y-%m-%d)
        date_one_year_ago=$(date --date='-1 year' +%Y-%m-%d)

    else

        date_one_month_ago=$(date -v -30d +%Y-%m-%d)
        date_one_year_ago=$(date -v -365d +%Y-%m-%d)

    fi

    # Count the number of revisions with dates between 1 year ago / 30 days ago, and today's date
    revisions_in_last_month=0
    revisions_in_last_year=0

    # Loop through the list of dates
    for (( j=0; j<${#revision_dates[@]}; j++))
    do

        # If the date is greater than 1 month ago, increment the counter
        if [[ "${revision_dates[$j]}" > "$date_one_month_ago" ]]
        then
            revisions_in_last_month=$((revisions_in_last_month+1))
        fi

        # If the date is greater than 1 year ago, increment the counter
        if [[ "${revision_dates[$j]}" > "$date_one_year_ago" ]]
        then
            revisions_in_last_year=$((revisions_in_last_year+1))
        fi

    done

    # Every 20th line, print the CSV header to the console again, to keep it in view
    if (( i % 20 == 0 ))
    then
        echo "$csv_header"
    fi

    # Create output string to reduce duplication
    output_string="$repo_index,$date_string,$time_string,$repo,$revisions_count,$newest_commit_date,$oldest_commit_date,$revisions_in_last_month,$revisions_in_last_year,$download_time,$download_revs_per_sec"

    # Output to the CSV file
    echo "$output_string" >> "$svn_stats_csv_file"

    # Output to the console to show progress to the anxious operator
    echo "$output_string"

done
