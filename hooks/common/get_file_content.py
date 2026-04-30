import sys


def search_file(tree, path):
    blob = None

    for blob in tree.traverse():
        if blob.path == path:
            break

        if blob.type == "tree":
            search_file(blob, path)
    else:
        blob = None

    return blob


def get_file_content(repo, branch, path):
    tree = repo.tree(branch)

    blob = search_file(tree, path)
    content = None

    if blob is not None:
        content = blob.data_stream.read().decode("ascii")

    return content


def get_local_file_content(path, log):
    try:
        with open(path) as f:
            return f.read()
    except Exception as e:
        log.error("Failed to read file '%s' from the current branch: %s" % (path, e))

        sys.exit(1)
