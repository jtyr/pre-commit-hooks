import os
import sys


def find_main_branch(repo, branch_name, remote_name, log):
    """Resolve the main branch head locally or by creating it from a remote ref.

    Exits with status 1 if the branch cannot be found.
    """
    for head in repo.heads:
        if head.name == branch_name:
            return head

    remote = None

    for r in repo.remotes:
        if r.name == remote_name:
            remote = r

            break

    if remote is None:
        log.error(
            "Main branch '%s' not found. Couldn't find the remote '%s'."
            % (branch_name, remote_name)
        )

        sys.exit(1)

    for ref in remote.refs:
        if ref.name == "%s/%s" % (remote_name, branch_name):
            try:
                return repo.create_head(ref.remote_head, ref)
            except Exception as e:
                log.error(
                    "Main branch '%s' not found. Failed to create head "
                    "from remote '%s': %s" % (branch_name, remote_name, e)
                )

                sys.exit(1)

    log.error(
        "Main branch '%s' not found. Failed to find it on the remote '%s'."
        % (branch_name, remote_name)
    )

    sys.exit(1)


def iter_commit_messages(repo, main_branch, current_branch, dir_path=None):
    """Yield commit messages on current_branch but not on main_branch.

    If dir_path is given, only yield messages of commits whose changes touched
    files under that directory. Paths are matched relative to the repo root.
    """
    rev_range = "%s..%s" % (main_branch.commit.hexsha, current_branch.commit.hexsha)

    kwargs = {}

    if dir_path:
        kwargs["paths"] = dir_path

    for commit in repo.iter_commits(rev_range, **kwargs):
        yield commit.message


def changed_paths_since_main(repo, main_branch):
    """Return absolute paths of files changed between main and the working tree.

    Includes both committed (main..HEAD) and staged-but-uncommitted changes.
    """
    paths = set()

    for d in main_branch.commit.diff(None):
        path = d.b_path or d.a_path

        if path:
            paths.add(os.path.join(repo.working_tree_dir, path))

    return paths


COMMIT_MSG_BASENAMES = {"COMMIT_EDITMSG", "MERGE_MSG", "SQUASH_MSG"}


def is_commit_msg_invocation(paths):
    """Detect whether the hook was invoked at the commit-msg stage.

    pre-commit passes a single path (typically .git/COMMIT_EDITMSG) at that
    stage. At pre-commit stage, paths are staged source files.
    """
    if len(paths) != 1:
        return False

    return os.path.basename(paths[0]) in COMMIT_MSG_BASENAMES
