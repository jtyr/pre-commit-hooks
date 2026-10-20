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
    rev: v1.9.0
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
- [`check-cargo-version`](#check-cargo-version)
- [`helm-unittest`](#helm-unittest)
- [`check-version`](#check-version)
- [`bats`](#bats)

---

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.9.0
    hooks:
      - id: check-helm-version
```

By default, the hook compares the version in the current branch to the version
in the `main` branch. The branch name can be changed by adding the `--branch`
argument:

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.9.0
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
    rev: v1.9.0
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
    rev: v1.9.0
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
    rev: v1.9.0
    hooks:
      - id: check-helm-version
        args:
          - --autofix
          - --autofix-portion=minor
```

The bump portion can also be derived from
[Conventional Commits](https://www.conventionalcommits.org/) messages by
setting `--autofix-strategy=conventional`. In this mode the hook ignores
`--autofix-portion` and instead inspects all commit messages between the main
branch and the current branch (filtered to commits that touched the chart
directory) plus the in-flight commit message, then picks the highest matching
bump:

| Commit message                                                                | Bump      |
| ----------------------------------------------------------------------------- | --------- |
| `feat!: ...`, `fix!: ...`, any type with `!`                                  | `major`   |
| Any message containing `BREAKING CHANGE:` or `BREAKING-CHANGE:` footer        | `major`   |
| `feat: ...`                                                                   | `minor`   |
| `fix: ...`, `perf: ...`                                                       | `patch`   |
| `chore:`, `docs:`, `style:`, `refactor:`, `revert:`, `test:`, `build:`, `ci:` | _no bump_ |

By default, valid Conventional Commits messages with no-bump types are
accepted without changing the version. The hook only fails when no commit in
the considered range carries a valid Conventional Commits message at all
(e.g. a free-form message like `wip`).

A manually bumped version that is at or above the version the Conventional
Commits messages would derive is accepted as-is. For example, if the
messages indicate a `minor` bump from `1.0.0` to `1.1.0` and the user has
already bumped the chart to `2.0.0`, the manual bump is preserved. Only
versions below the derived minimum trigger a failure (or autofix to that
minimum, with `--autofix`).

To require at least one bump-eligible message (i.e. fail on `chore:`-only
ranges), pass `--conventional-strict`:

```yaml
- id: check-helm-version
  args:
    - --autofix
    - --autofix-strategy=conventional
    - --conventional-strict
```

There is no fallback to `--autofix-portion` in conventional mode - either a
bump-eligible message determines the bump, or no bump happens.

If the chart does not exist on the main branch, the baseline version is
treated as `0.0.0`.

The conventional strategy runs at the `commit-msg` stage so that the in-flight
commit message participates in the decision. This requires the `commit-msg`
git hook to be installed, which is opted into via `default_install_hook_types`
in the `.pre-commit-config.yaml`:

```yaml
default_install_hook_types:
  - pre-commit
  - commit-msg

repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.9.0
    hooks:
      - id: check-helm-version
        args:
          - --autofix
          - --autofix-strategy=conventional
```

After changing `default_install_hook_types`, run `pre-commit install` once so
that the new git hook is installed.

The conventional strategy also runs at the `pre-commit` stage when pre-commit
is invoked with `--from-ref` and `--to-ref` (or at the `pre-push` stage),
i.e. when pre-commit sets `PRE_COMMIT_FROM_REF` / `PRE_COMMIT_TO_REF`. This
makes branch-wide validation possible:

```bash
pre-commit run check-helm-version --from-ref origin/main --to-ref HEAD
```

In this mode there is no in-flight commit message; the bump is derived
purely from path-filtered commit messages between the main branch and the
current branch. Combined with the per-chart scoping below, the validation
run mirrors the behavior of running each individual `git commit` on the
branch.

The in-flight commit message is only attached to charts that the commit
actually touches. A `feat:` commit modifying only chart A will not bump
chart B even if chart B has unrelated changes earlier on the branch.

### `check-cargo-version`

This hook checks if the version of a Rust crate (Cargo package) was incremented
when the crate's code changed. This helps to prevent the `cargo publish` to fail
if the same version of the crate already exists in the registry (e.g.
[crates.io](https://crates.io) or [Kellnr](https://github.com/kellnr/kellnr)).

The hook finds the crate that owns each changed file by walking up the directory
tree to the nearest `Cargo.toml` with a `[package]` section. Which version is
then checked depends on the crate's `Cargo.toml`:

- `version = "x.y.z"` - the version of the crate itself.
- `version.workspace = true` - the version in the `[workspace.package]` section
  of the workspace root `Cargo.toml`. It's shared by all crates inheriting it so
  it's checked only once.
- no `version` - the crate is skipped. Remove the `version` from the crate if
  you don't want its version to be managed.

The `publish` field is not taken into account.

Changes of a nested crate (e.g. `crates/foo` inside of the root package) belong
only to the nested crate. Deleting a whole crate doesn't require a version bump
of its parent crate.

By default, only changes of `*.rs` files (including `build.rs`, `tests/`,
`benches/` and `examples/`) and `Cargo.toml` files require a version bump. This
can be changed with the `--include` and `--exclude` arguments that take a
regexp matched against the repo-relative path of each changed file. Use those
arguments instead of the `files` and `exclude` options of the hook so the same
filter is applied at both the `pre-commit` and the `commit-msg` stage:

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.9.0
    hooks:
      - id: check-cargo-version
        args:
          - --exclude=(^|/)(tests|benches|examples)/
```

The hook also checks that the versions of the checked crates in the
`Cargo.lock` (if it exists) match the version in the `Cargo.toml`. With the
`--autofix` argument, the `Cargo.lock` is updated together with the version so
no `cargo update --workspace` is needed. Version requirements of other crates
depending on the bumped crate are not updated.

#### Usage

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.9.0
    hooks:
      - id: check-cargo-version
        args:
          - --autofix
```

Bump the version based on the
[Conventional Commits](https://www.conventionalcommits.org/) messages:

```yaml
default_install_hook_types:
  - pre-commit
  - commit-msg

repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.9.0
    hooks:
      - id: check-cargo-version
        args:
          - --autofix
          - --autofix-strategy=conventional
```

The bumps follow the classic Conventional Commits rules, so a breaking change
bumps the `major` portion even for `0.x.y` versions.

Please refer to the `check-helm-version` above for more details about the
usage.

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
    rev: v1.9.0
    hooks:
      - id: helm-unittest
```

Specify a custom charts directory:

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.9.0
    hooks:
      - id: helm-unittest
        args:
          - --charts-dir=my-charts
```

Use custom test directory and file pattern:

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.9.0
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
    rev: v1.9.0
    hooks:
      - id: helm-unittest
        args:
          - --failfast
```

Enable debug output:

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.9.0
    hooks:
      - id: helm-unittest
        args:
          - --debug
```

Test library charts using helper charts:

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.9.0
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
    rev: v1.9.0
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
    rev: v1.9.0
    hooks:
      - id: check-version
```

Use different version file (e.g. `VERSION` instead of the default `.version`)
and check version when any file changes but the `.gitignore` and `README.md`
file:

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.9.0
    hooks:
      - id: check-version
        args:
          - --version-file=VERSION
        files: ^(?!(.gitignore|README.md)).*$
```

Please refer to the `check-helm-version` above for more details about the usage.

### `bats`

This hook runs [bats](https://github.com/bats-core/bats-core) tests for each
changed shell script. For every `.sh` file passed by `pre-commit`, the hook
looks for a companion bats file at a template-resolved location and runs bats
on it. Shell scripts without a companion bats file are silently skipped.

`bats-core` must be installed on the machine running the hook (the hook does
not install it).

#### Usage

Side-by-side layout (`foo.sh` + `foo.bats` in the same directory), which is the
default:

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.9.0
    hooks:
      - id: bats
```

Sibling `tests/` directory (`scripts/foo.sh` + `tests/foo.bats` relative to the
script):

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.9.0
    hooks:
      - id: bats
        args:
          - --pattern=../tests/{name}.bats
```

Centralised tests directory at the repo root (`{root}` expands to the cwd when
`pre-commit` runs the hook, which is the root of the repo containing
`.pre-commit-config.yaml`):

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.9.0
    hooks:
      - id: bats
        args:
          - --pattern={root}/tests/{name}.bats
```

#### Pattern placeholders

- `{name}` - the basename of the shell script without the `.sh` extension.
- `{root}` - the absolute path of the directory where `pre-commit` runs the
  hook (equivalent to the directory containing `.pre-commit-config.yaml`).

When the expanded path is not absolute it is interpreted relative to the
directory of the shell script.

#### Arguments

- `-p`, `--pattern PATTERN` - template for the companion bats file location
  (default: `{name}.bats`).
- `-d`, `--debug` - enable debug output.

## Author

Jiri Tyr

## License

MIT
