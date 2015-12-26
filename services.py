import os
import git
import json

from datetime import datetime, timedelta
from itertools import chain
from github import Github

from pybitbucket import bitbucket
from pybitbucket.repository import Repository, RepositoryRole
from pybitbucket.auth import BasicAuthenticator
from pybitbucket.team import Team, TeamRole


class BaseCommitDiscovery:
    cache_file = NotImplemented
    reload_after = timedelta(hours=12)
    debug = True

    def get_commits(self):
        """
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
        if self.cached_exists() and self.cache_is_fresh():
            with open(self.cache_file, 'r') as file:
                return json.loads(file.read())

        commits = self.fetch_commits()
        with open(self.cache_file, 'w') as file:
            file.write(json.dumps(commits, indent=4))
        return commits

    def fetch_commits(self):
        raise NotImplementedError

    def cached_exists(self):
        return os.path.exists(self.cache_file)

    def cache_is_fresh(self):
        modified = datetime.fromtimestamp(os.stat(self.cache_file).st_mtime)
        return datetime.now() - modified < self.reload_after


class GithubDiscovery(BaseCommitDiscovery):
    cache_file = 'cache/github_commits.json'

    def __init__(self, token, username):
        self.api = Github(token)
        self.username = username
        self.token = token

    def fetch_commits(self):
        user = self.api.get_user()
        repos = user.get_repos()

        commits = []

        for repo in repos:
            is_public = not repo.private
            repo_name = repo.full_name

            for commit in repo.get_commits(author=self.username):
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
                commits.append(commit_data)

                if self.debug:
                    print(commit.commit.sha, commit.commit.message)
        return commits


class ClonedRepositoryDiscovery(BaseCommitDiscovery):
    """
    This is mixin for discoveries that are based on cloning repositories
    """
    repo_dir = 'repos'
    discovery_dir = ''
    user_emails = []

    def get_repo_path(self, name):
        """
        Args:
            name: name of repository
        Returns: path to repository
        """
        return os.path.join(self.repo_dir, self.discovery_dir, name)

    def get_commits_by_repo(self, repo_path, is_public=True, name=None):
        """
        Args:
            is_public: is this public repository
            name: name of the repository
            repo_path: path to repo
        Returns:
            list of comments
        """
        repo_git = git.Git(repo_path)
        repo = git.Repo(repo_path)
        revs = set()
        commits = []

        for email in self.user_emails:
            logs = repo_git.log(
                '--all',
                '--pretty=%H',
                '--author={}'.format(email))
            revs.update(logs.splitlines())

        for rev in revs:
            commit = repo.rev_parse(rev)
            created = datetime.fromtimestamp(commit.authored_date)
            commits.append({
                'datetime': created.isoformat(),
                'message': commit.message,
                'hash': commit.hexsha,
                'public': is_public,
                'repo': name
            })

        return commits

    def fetch_commits(self):  # this is still abstract class
        raise NotImplementedError


class BitbucketDiscovery(ClonedRepositoryDiscovery):
    discovery_dir = 'bitbucket'
    cache_file = 'cache/bitbucket_commits.json'

    def __init__(self, username, password, email, user_emails):
        self.client = bitbucket.Client(
            BasicAuthenticator(username, password, email)
        )
        self.user_emails = user_emails

    def fetch_commits(self):
        commits = []
        teams = chain(
            Team.find_teams_for_role(role=TeamRole.ADMIN, client=self.client),
            Team.find_teams_for_role(role=TeamRole.CONTRIBUTOR, client=self.client),  # noqa
            Team.find_teams_for_role(role=TeamRole.MEMBER, client=self.client),
        )

        repo_names = set()
        for team in teams:
            for repo in team.repositories():
                if isinstance(repo, Repository):
                    repo_names.add(repo.full_name)

        team_repos = [
            Repository.find_repository_by_full_name(name, self.client)
            for name in repo_names
        ]

        repos = chain(
            Repository.find_my_repositories_by_role(
                    RepositoryRole.OWNER, self.client),
            Repository.find_my_repositories_by_role(
                    RepositoryRole.ADMIN, self.client),
            Repository.find_my_repositories_by_role(
                    RepositoryRole.CONTRIBUTOR, self.client),
            Repository.find_my_repositories_by_role(
                    RepositoryRole.MEMBER, self.client),
            team_repos
        )

        for repo in repos:
            is_public = not repo.is_private
            repo_name = repo.full_name
            repo_dir = self.get_repo_path(repo_name)

            if os.path.exists(repo_dir):
                git.Repo(repo_dir).remote().pull()
            else:
                git.Repo.clone_from(repo.clone['ssh'], repo_dir)

            commits.extend(
                self.get_commits_by_repo(repo_dir, is_public, repo_name)
            )

        return commits
