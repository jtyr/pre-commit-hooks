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
    rev: v1.4.0
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
prevent the Helm chart push to fail if there already exists a Helm chart with
the same version in the registry. If the registry allows to overwrite an
existing Helm chart version, this hook helps to prevent the overwrite.

#### Usage

Supported `pre-commit` hooks:

- [`docker-image`](#docker-image)
- [`check-helm-version`](#check-helm-version)
- [`helm-unittest`](#helm-unittest)
- [`check-version`](#check-version)

---

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.4.0
    hooks:
      - id: check-helm-version
```

By default, the hook compares the version in the current branch to the version
in the `main` branch. The branch name can be changed by adding the `--branch`
argument:

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.4.0
    hooks:
      - id: check-helm-version
        args:
          - --branch=default
```

If the branch cannot be found locally, the hook will try to create the branch
head from the remote. The remote name can be set via `--remote` argument:

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.4.0
    hooks:
      - id: check-helm-version
        args:
          - --remote=upstream
          - --branch=default
```

It's also possible to autofix the version incrementation by specifying the
`--autofix` argument:

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.4.0
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
    rev: v1.4.0
    hooks:
      - id: check-helm-version
        args:
          - --autofix
          - --autofix-portion=minor
```

### `helm-unittest`

This hook runs Helm chart unit tests using the [Helm Unittest
plugin](https://github.com/helm-unittest/helm-unittest). It automatically
detects which Helm charts have been modified based on the changed files and runs
the unit tests for those charts. The hook will fail if any unit tests fail.

#### Prerequisites

The Helm Unittest plugin must be installed:

```bash
helm plugin install https://github.com/helm-unittest/helm-unittest
```

#### Usage

Basic usage with default settings (charts in `charts/` directory, tests in
`tests/unittest/` within each chart):

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.4.0
    hooks:
      - id: helm-unittest
```

Specify a custom charts directory:

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.4.0
    hooks:
      - id: helm-unittest
        args:
          - --charts-dir=my-charts
```

Use custom test directory and file pattern:

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.4.0
    hooks:
      - id: helm-unittest
        args:
          - --tests-path=tests/unit
          - --test-files=*.test.yaml
```

Stop on first test failure:

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.4.0
    hooks:
      - id: helm-unittest
        args:
          - --failfast
```

Enable debug output:

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.4.0
    hooks:
      - id: helm-unittest
        args:
          - --debug
```

Test library charts using helper charts:

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.4.0
    hooks:
      - id: helm-unittest
        args:
          - --path-sub-pattern=^charts/(.*),helper-charts/\1-test
```

#### Library Chart Support

Library charts (`type: library`) cannot be templated directly by Helm and
therefore cannot be tested directly. To test library charts, you can use the
`--path-sub-pattern` argument to redirect the tests to use a helper chart that
wraps the library chart.

By default, the hook is configured with
`--path-sub-pattern=^charts/(libchart),helper-charts/\1` which will redirect any
library chart named `libchart` in the `charts/` directory to use a helper chart
in `helper-charts/libchart/` for testing. The tests for the library chart should
be placed in the helper chart's test directory. You can customize this pattern
to match your project structure.

**Default behavior:**

If you have a library chart at `charts/libchart/`, the hook will automatically
use `helper-charts/libchart/` for testing and will look for test files in
`helper-charts/libchart/tests/unittest/` directory.

**Custom pattern example:**

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.4.0
    hooks:
      - id: helm-unittest
        args:
          - --path-sub-pattern=^charts/(.*),helper-charts/\1
```

**Example setup:**

```text
charts/
├── libchart/                # Library chart (matches default pattern)
│   ├── Chart.yaml           # type: library
│   └── templates/
│       └── _helpers.tpl
helper-charts/
└── libchart/                # Helper chart that uses the library
    ├── Chart.yaml           # type: application
    ├── charts/
    │   └── libchart/        # Symlink to the library chart
    ├── templates/
    │   └── test-resources.yaml
    └── tests/
        └── unittest/
            └── helpers_test.yaml  # Tests for library chart
```

**Usage:**

```yaml
- id: helm-unittest  # Uses default pattern, no args needed for libchart
```

This pattern will:

1. Detect changes in `charts/libchart/`
2. Look for tests in `helper-charts/libchart/tests/unittest/`
3. Run `helm unittest` against `helper-charts/libchart/` using the tests from
   the helper chart

#### Test Structure

The hook expects unit tests to be organized as follows:

```text
charts/
├── my-chart/
│   ├── Chart.yaml
│   ├── values.yaml
│   ├── templates/
│   │   └── deployment.yaml
│   └── tests/
│       └── unittest/
│           ├── deployment_test.yaml
│           └── service_test.yaml
└── another-chart/
    ├── Chart.yaml
    └── tests/
        └── unittest/
            └── chart_test.yaml
```

#### Arguments

- `--charts-dir` (`-c`): Directory containing Helm charts (default: `charts`)
- `--tests-path` (`-t`): Relative path to test files within chart (default:
  `tests/unittest`)
- `--test-files` (`-f`): Glob pattern for test files (default: `*.yaml`)
- `--failfast`: Stop on first test failure
- `--debug` (`-d`): Enable debug output
- `--path-sub-pattern`: Regexp substitution pattern for chart paths, useful for
  library charts (format: `pattern,replacement`, default:
  `^charts/(libchart),helper-charts/\1`)

### `check-version`

This hook is almost the same like the `check-helm-version` with the difference
that it changes version in a plain text file (e.g. `.version`).

#### Usage

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.4.0
    hooks:
      - id: check-version
```

Use different version file (e.g. `VERSION` instead of the default `.version`)
and check version when any file changes but the `.gitignore` and `README.md`
file:

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.4.0
    hooks:
      - id: check-version
        args:
          - --version-file=VERSION
        files: ^(?!(.gitignore|README.md)).*$
```

Please refer to the `check-helm-version` above for more details about the usage.

## Author

Jiri Tyr

## License

MIT
