# pre-commit-hooks

This repository contains Jiri Tyr's `pre-commit` hooks.

## Hooks

### `docker-image`

This hook is an extension of the original `pre-commit` implementation of running
checks in a [Docker image](https://pre-commit.com/index.html#docker_image). It's
using the actual `pre-commit` code but it extends it with functionality for a
better detection of the "Docker in Docker" scenario (e.g. when running in a
custom Docker image in GitHub Workflows). The detection comprise of these
checks:

- [Using Control Groups](https://www.baeldung.com/linux/is-process-running-inside-container#using-control-groups)
- [Existence of `.dockerenv`](https://www.baeldung.com/linux/is-process-running-inside-container#existence-of-dockerenv)
- [Using CPU Scheduling Info](https://www.baeldung.com/linux/is-process-running-inside-container#using-cpu-scheduling-info)

#### Usage

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.3.5
    hooks:
      - id: docker-image
        name: Run /tools/validate.sh in container
        args:
          - my_user/my_image:latest
          - -c
          - /tools/validate.sh
        pass_filenames: false
```

### `check-helm-version`

This hook checks if the Helm chart version was incremented or not. This helps to
prevent the Helm chart push to fail if there already exists a Helm chart with the
same version in the registry. If the registry allows to overwrite an existing
Helm chart version, this hook helps to prevent the overwrite.

#### Usage

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.3.5
    hooks:
      - id: check-helm-version
```

By default, the hook compares the version in the current branch to the
version in the `main` branch. The branch name can be changed by adding
the `--branch` argument:

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.3.5
    hooks:
      - id: check-helm-version
        args:
          - --branch=default
```

If the branch cannot be found locally, the hook will try to create the
branch head from the remote. The remote name can be set via `--remote`
argument:

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.3.5
    hooks:
      - id: check-helm-version
        args:
          - --remote=upstream
          - --branch=default
```

It's also possible to autofix the version incrementation by specifying
the `--autofix` argument:

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.3.5
    hooks:
      - id: check-helm-version
        args:
          - --autofix
```

By default, the `patch` portion of the version is incremented. Different
portion (`major`, `minor`, `prerelease` and `build`) can be specified
with the `--autofix-portion` argument:

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.3.5
    hooks:
      - id: check-helm-version
        args:
          - --autofix
          - --autofix-portion=minor
```

### `check-version`

This hook is almost the same like the `check-helm-version` with the
difference that it changes version in a plain text file ((e.g.
`.version`).

#### Usage

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.3.5
    hooks:
      - id: check-version
```

Use different version file (e.g. `VERSION` instead of the default
`.version`):

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.3.5
    hooks:
      - id: check-version
        args:
          - --version-file=VERSION
        files: ^.*/VERSION$
```

Please refer to the `check-helm-version` above for more details about
the usage.

## Author

Jiri Tyr

## License

MIT
