"""Helpers for tests that need a real git repository."""

import os
import shutil
import tempfile

from git import Repo

# Strip inherited GIT_* env vars at import time. When the tests are invoked
# from within a `git commit` or `pre-commit run` (e.g. as a pre-commit hook),
# variables like GIT_DIR / GIT_WORK_TREE / GIT_INDEX_FILE point at the outer
# repository and would make subprocess git calls in the fixture operate on
# the wrong repo.
for _key in [k for k in os.environ if k.startswith("GIT_")]:
    del os.environ[_key]


class GitRepoFixture:
    """A temporary git repository.

    Creates a repo with a `main` branch holding an initial commit. Helpers are
    provided to write files, stage them, commit, and switch branches.
    """

    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self.repo = Repo.init(self.dir, initial_branch="main")

        with self.repo.config_writer() as cfg:
            cfg.set_value("user", "email", "test@example.com")
            cfg.set_value("user", "name", "Test")
            cfg.set_value("commit", "gpgsign", "false")

        self.write("README.md", "# test\n")
        self.add("README.md")
        self.commit("initial commit")

    @property
    def main(self):
        return self.repo.heads["main"]

    def write(self, rel_path, content):
        path = os.path.join(self.dir, rel_path)
        parent = os.path.dirname(path)

        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)

        with open(path, "w") as f:
            f.write(content)

        return path

    def remove(self, rel_path):
        path = os.path.join(self.dir, rel_path)

        if os.path.isfile(path):
            os.remove(path)

    def add(self, *rel_paths):
        self.repo.index.add(list(rel_paths))

    def commit(self, message):
        return self.repo.index.commit(message)

    def create_branch(self, name, checkout=True):
        head = self.repo.create_head(name)

        if checkout:
            head.checkout()

        return head

    def checkout(self, name):
        self.repo.heads[name].checkout()

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)
