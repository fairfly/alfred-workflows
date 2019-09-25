import re
import os
import sys
import json
import requests
import webbrowser

from github.GithubException import GithubException

from github import Github


class FFGitHub:
    FF_TASK_PATTERN = r'(FF[\s*\-\s*]*)(?P<task>\d*)(?P<desc>.*)'

    def __init__(self, repo_name):
        github_token = os.environ.get('GITHUB_ACCESS_TOKEN')
        self.github = Github(login_or_token=github_token)
        self.main_repo = self.get_repo(repo_name)

    def get_repo(self, repo_name):
        for repo in self.github.get_user().get_repos():
            if repo.name == repo_name:
                return repo
        raise Exception("Repository not found. [%s]" % repo_name)

    def create_pull_request(self, is_deploy_sequence, body="", from_branch="staging", to_branch="master"):
        if is_deploy_sequence:
            title = "Automated deploy" if from_branch_name == "staging" else "Automated HOTFIX deploy"
        else:
            title = "Automated PR"

        try:
            pr = self.main_repo.create_pull(title=title, body=body, base=to_branch, head=from_branch)
        except GithubException as e:
            prs = self.main_repo.get_pulls(base=to_branch, head="fairfly:%s" % from_branch, direction="desc")
            if (prs.totalCount > 0):
                pr = prs[0]
            else:
                raise Exception("PR not created for %s, %s" % (from_branch, get_gihub_error(e)))            

        return self.update_body_with_commits(pr, title_from_commit=not is_deploy_sequence)

    def update_body_with_commits(self, pr, title_from_commit=False):
        commits = pr.get_commits()
        main_commit_title = None
        body = set()
        for pr_commit in commits:
            message = pr_commit.commit.message

            if "Merge pull request #" in message:
                continue

            if "Merge remote" in message:
                continue

            if "Merge branch" in message:
                continue

            match = re.search(self.FF_TASK_PATTERN, message)
            if match:
                task_number = match.group('task')
                task_desc = match.group('desc')

                if not main_commit_title:
                    main_commit_title = "FF-%s %s" % (task_number, task_desc)
                if task_number:
                    body.add("https://oversee.atlassian.net/browse/FF-%s" % task_number)
            else:
                body.add(str(message))

        if main_commit_title is None:
            main_commit_title = commits[0].commit.message

        raw_body = ""
        list_body = list(body)
        list_body.reverse()
        for url in list_body:
            raw_body += url + '\n'
            
        buddy_acceptance_url = os.environ.get('BUDDY_EXECUTION_URL')
        if buddy_acceptance_url:
            raw_body += "Acceptance Checker: %s\nResults: https://s3.console.aws.amazon.com/s3/buckets/fairfly-logs/%s/\n" % (buddy_acceptance_url, os.environ.get('ACCEPTANCE_RUN_FULL_PATH'))

        if title_from_commit:
            pr.edit(title=main_commit_title, body=pr.body + '\n' + raw_body)
        else:
            pr.edit(title=pr.title, body=pr.body + '\n' + raw_body)

        print(pr)
        return pr

def send_slack_notification(text, channel, username=None, attachments=None, emoji=None):
    """
    @param text:
    @param channel:
    @param username:
    @type attachments: list
    @param emoji: the emoji to send with the message
    :return: the channel on which the message was sent  # useful for testing
    """
    sender_name = "Acceptance Checker" if os.environ.get('BUDDY_EXECUTION_URL') else "Alfred"
    params = {"text": text,
              'username': sender_name}

    if channel:
        params['channel'] = '#%s' % channel

    if username:
        params['username'] = username

    if attachments:
        params['attachments'] = attachments

    if emoji:
        params['icon_emoji'] = emoji

    requests.post('https://hooks.slack.com/services/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',
                  {'payload': json.dumps(params)})

    return channel

def get_gihub_error(e):
    error = e.args[1]['errors'][0]
    return error.get('message') or error['code']


if __name__ == "__main__":
    try:
        repo_name = os.environ.get('project') or sys.argv[1]
        from_branch_name = os.environ.get('from_branch') or sys.argv[2]
        into_branch_name = os.environ.get('into_branch') or sys.argv[3]
        is_hotfix = os.environ.get('is_hotfix')
        open_conf = os.environ.get('open_conf')

        ff_github = FFGitHub(repo_name)
        pull_request = ff_github.create_pull_request(is_deploy_sequence=bool(open_conf), from_branch=from_branch_name, to_branch=into_branch_name)
        
        # Slack alert
        send_slack_notification("[%s] Pull request from %s created\n%s" % (repo_name, from_branch_name, pull_request.html_url), "dev", emoji=":rocket:")
        
        webbrowser.open(pull_request.html_url)

        print("Initiated [%s] PR: Master <- %s" % (repo_name.title(), from_branch_name))
    except GithubException as e:
        print(e, get_gihub_error(e))
    except Exception as e:
        print(e)
