import secrets
import json
import dateutil.parser

from collections import defaultdict
from github import Github


def get_github_commits(token, username):
    """
    Args:
        username: gh username
        token: gh personal token

    Returns:
        [
            {
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
        ]
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
            }
            print(commit.commit.sha, commit.commit.message)

            if is_public:
                commit_data['message'] = commit.commit.message
                commit_data['repo'] = repo_name
                commit_data['link'] = commit.html_url
            commits.append(commit_data)

    return commits


def get_project_stats(commits):
    """
    Args:
        commits: list of commits, see ``get_github_commits`` for format

    Returns: {'project': commit_count}
    """
    project_stats = defaultdict(lambda: 0)
    project_commits = filter(lambda c: 'repo_name' in c, commits)

    for commit in project_commits:
        project_stats[commit['repo']] += 1
    return project_stats


def get_daily_stats(commits):
    """
    Args:
        commits: list of commits, see ``get_github_commits`` for format

    Returns: {datetime: number of commits}
    """
    daily_stats = defaultdict(lambda: 0)
    for commit in commits:
        # sanitize datetime iso datetime to iso date:
        commit_date = dateutil.parser.parse(commit['datetime']).date()
        daily_stats[commit_date.isoformat()] += 1
    return daily_stats


if __name__ == '__main__':
    github_commits = get_github_commits(
        secrets.personal_token,
        secrets.username
    )

    with open('cache/github_commits.json', 'w') as file:
        file.write(json.dumps(github_commits, indent=4))

    with open('cache/daily_stats.json', 'w') as file:
        file.write(json.dumps(get_daily_stats(github_commits), indent=4))

    with open('cache/project_stats.json', 'w') as file:
        file.write(json.dumps(get_project_stats(github_commits), indent=4))
