import secrets
import json
import dateutil.parser
import csv
import services

from getpass import getpass
from collections import defaultdict


def get_project_stats(commits):
    """
    Args:
        commits: dict of commits, see ``get_github_commits`` for format

    Returns: {'project': commit_count}
    """
    project_stats = defaultdict(lambda: 0)

    for commit in commits:
        project_stats[commit['repo']] += 1
    return project_stats


def get_daily_stats(commits):
    """
    Args:
        commits: dict of commits, see ``get_github_commits`` for format

    Returns: {datetime: number of commits}
    """
    daily_stats = defaultdict(lambda: 0)
    for commit in commits:
        # sanitize datetime to just a iso date:
        commit_date = dateutil.parser.parse(commit['datetime']).date()
        daily_stats[commit_date.isoformat()] += 1
    return daily_stats


if __name__ == '__main__':
    bitbucket_commits = services.BitbucketDiscovery(
        secrets.bitbucket_username,
        getpass('Bitbucket password: '),
        secrets.bitbucket_email,
        secrets.git_emails,
    ).get_commits()

    github_commits = services.GithubDiscovery(
        secrets.github_personal_token,
        secrets.github_username
    ).get_commits()

    # save all commits stats
    all_commits = bitbucket_commits + github_commits
    with open('daily_stats.csv', 'w') as csv_file:
        data = get_daily_stats(all_commits)
        writer = csv.writer(csv_file)
        writer.writerow(['date', 'commits'])
        writer.writerows(data.items())

    with open('project_stats.json', 'w') as file:
        file.write(json.dumps(get_project_stats(all_commits), indent=4))
