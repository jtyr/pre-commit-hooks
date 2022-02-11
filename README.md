# pre-commit-hooks

This repository contains Jiri Tyr's `pre-commit` hooks.

## Hooks

### `docker-image`

This hook is an extension of the original `pre-commit` implementation of running
checks in a [Docker image](https://pre-commit.com/index.html#docker_image). It's
using the actual `pre-commit` code but it extends it with functionality for a
better detection of the "Docker in Docker" scenario. The detection comprise of
these checks:

- [Using Control Groups](https://www.baeldung.com/linux/is-process-running-inside-container#using-control-groups)
- [Existence of `.dockerenv`](https://www.baeldung.com/linux/is-process-running-inside-container#existence-of-dockerenv)
- [Using CPU Scheduling Info](https://www.baeldung.com/linux/is-process-running-inside-container#using-cpu-scheduling-info)

#### Usage

```yaml
repos:
  - repo: https://github.com/jtyr/pre-commit-hooks
    rev: v1.0.0
    hooks:
      - id: docker-image
        name: Run /tools/validate.sh in container
        args:
          - my_user/my_image:latest
          - -c
          - /tools/validate.sh
        pass_filenames: false
```

## Author

Jiri Tyr

## License

MIT
