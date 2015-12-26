import secrets
import json
import dateutil.parser
import csv
import os
import git

from getpass import getpass
from datetime import datetime, timedelta
from collections import defaultdict
from itertools import chain
from github import Github

from pybitbucket import bitbucket
from pybitbucket.repository import Repository, RepositoryRole
from pybitbucket.auth import BasicAuthenticator
from pybitbucket.team import Team, TeamRole


GH_COMMITS_FILENAME = 'cache/github_commits.json'
BB_COMMITS_FILENAME = 'cache/bitbucket_commits.json'
REPOS_CLONE = 'repos/'
RELOAD_AFTER = timedelta(hours=6)


def age_of_file(filename):
    """
    Args:
        filename: path to file

    Returns:
        timedelta() object representing the age of file
        None if file does not exist
    """
    if not os.path.exists(filename):
        return None

    modified = datetime.fromtimestamp(os.stat(filename).st_mtime)
    return datetime.now() - modified


def cached_file_exists(filename):
    return (
        os.path.exists(filename) and age_of_file(filename) < RELOAD_AFTER
    )


def get_github_commits(token, username):
    """
    Args:
        username: gh username
        token: gh personal token

    Returns:
        {
            hex: {
                "datetime": utc datetime,
                "hash": commit hash string,
                "public": bool, if this commit was in public repository,
                "additions": number of lines added,
                "deletions": number of lines deleted,

                # for public repos following params will be filled
                "message": string with the commit message,
                "repo_name": string with repository name,
                "link": link to github page with this commit
            }
        }
    """
    commits = []

    api = Github(token)
    user = api.get_user()
    repos = user.get_repos()

    for repo in repos:
        is_public = not repo.private
        repo_name = repo.full_name

        for commit in repo.get_commits(author=username):
            commit_data = {
                'datetime': commit.commit.author.date.isoformat(),
                'hash': commit.commit.sha,
                'public': is_public,
                'additions': commit.stats.additions,
                'deletions': commit.stats.deletions,
                'message': commit.commit.message,
                'repo': repo_name,
                'link': commit.html_url,
            }

            print(commit.commit.sha, commit.commit.message)
            commits.append(commit_data)

    return commits


def get_bitbucket_commits(username, password, email):
    commits = {}
    c = bitbucket.Client(BasicAuthenticator(username, password, email))

    teams = Team.find_teams_for_role(role=TeamRole.MEMBER, client=c)
    repo_names = []
    # sadly team.repositories does not return repository object which would
    # filter commits by author
    for team in teams:
        for repo in team.repositories():
            if isinstance(repo, Repository):
                repo_names.append(repo.full_name)

    team_repos = [Repository.find_repository_by_full_name(name, c)
                  for name in repo_names]

    repos = chain(
        Repository.find_my_repositories_by_role(RepositoryRole.OWNER, c),
        Repository.find_my_repositories_by_role(RepositoryRole.ADMIN, c),
        Repository.find_my_repositories_by_role(RepositoryRole.CONTRIBUTOR, c),
        Repository.find_my_repositories_by_role(RepositoryRole.MEMBER, c),
        team_repos
    )

    for repo in repos:
        is_public = not repo.is_private
        repo_name = repo.full_name
        repo_dir = os.path.join(REPOS_CLONE, repo_name)

        if os.path.exists(repo_dir):
            repo = git.Repo(repo_dir)
            repo.remote().pull()
        else:
            repo = git.Repo.clone_from(repo.clone['ssh'], repo_dir)

        for email in secrets.git_emails:
            for commit in repo.iter_commits(author=email):
                print(commit.hexsha, commit.message)
                created = datetime.fromtimestamp(commit.authored_date)
                commits[commit.hexsha] = {
                    'datetime': created.isoformat(),
                    'message': commit.message,
                    'hash': commit.hexsha,
                    'public': is_public,
                    'repo': repo_name
                }
    return commits


def get_project_stats(commits):
    """
    Args:
        commits: dict of commits, see ``get_github_commits`` for format

    Returns: {'project': commit_count}
    """
    project_stats = defaultdict(lambda: 0)

    for hex_sha, commit in commits.items():
        project_stats[commit['repo']] += 1
    return project_stats


def get_daily_stats(commits):
    """
    Args:
        commits: dict of commits, see ``get_github_commits`` for format

    Returns: {datetime: number of commits}
    """
    daily_stats = defaultdict(lambda: 0)
    for hex_sha, commit in commits.items():
        # sanitize datetime iso datetime to iso date:
        commit_date = dateutil.parser.parse(commit['datetime']).date()
        daily_stats[commit_date.isoformat()] += 1
    return daily_stats


if __name__ == '__main__':
    # deal with bitbucket:
    if cached_file_exists(BB_COMMITS_FILENAME):
        with open(BB_COMMITS_FILENAME, 'r') as file:
            bitbucket_commits = json.loads(file.read())
    else:
        bitbucket_commits = get_bitbucket_commits(
            secrets.bitbucket_username,
            getpass('Bitbucket password: '),
            secrets.bitbucket_email
        )
        with open(BB_COMMITS_FILENAME, 'w') as file:
            file.write(json.dumps(bitbucket_commits, indent=4))

    # deal with github shit:
    if cached_file_exists(GH_COMMITS_FILENAME):
        with open(GH_COMMITS_FILENAME, 'r') as file:
            github_commits = json.loads(file.read())
    else:
        github_commits = get_github_commits(
            secrets.personal_token,
            secrets.username
        )
        with open(GH_COMMITS_FILENAME, 'w') as file:
            file.write(json.dumps(github_commits, indent=4))

    # save all commits stats
    all_commits = bitbucket_commits + github_commits
    with open('cache/daily_stats.csv', 'w') as csv_file:
        data = get_daily_stats(all_commits)
        writer = csv.writer(csv_file)
        writer.writerow(['date', 'commits'])
        writer.writerows(data.items())
