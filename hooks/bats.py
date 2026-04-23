import argparse
import logging
import subprocess
import sys
from pathlib import Path


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run bats tests for each changed shell script's companion bats file."
    )

    parser.add_argument(
        "-p",
        "--pattern",
        metavar="PATTERN",
        help=(
            "template for the companion bats file location. Supports "
            "{name} (basename of the shell script without the .sh "
            "extension) and {root} (absolute path of the config root, "
            "i.e. the cwd when the hook runs). When the expanded path "
            "is not absolute, it is interpreted relative to the "
            "directory of the shell script (default: %(default)s)"
        ),
        default="{name}.bats",
    )
    parser.add_argument(
        "-d",
        "--debug",
        help="enable debug output",
        action="store_true",
    )

    parser.add_argument(
        "files",
        nargs="*",
        help="files that have changed (provided by pre-commit)",
    )

    return parser.parse_args()


def get_logger(debug):
    """Set up logging configuration."""
    level = logging.DEBUG if debug else logging.INFO
    format_str = "[%(asctime)s] %(levelname)s: %(message)s"
    logging.basicConfig(level=level, format=format_str)
    return logging.getLogger(__name__)


def resolve_pattern(pattern, sh_path, root):
    """
    Resolve the companion bats path for a shell script.

    Args:
        pattern: template string with {name} and {root} placeholders
        sh_path: Path to the shell script
        root: absolute Path of the config root

    Returns:
        Absolute Path of the candidate bats file. Does not check
        whether the file exists.
    """
    expanded = pattern.format(name=sh_path.stem, root=str(root))
    candidate = Path(expanded)

    if not candidate.is_absolute():
        candidate = sh_path.parent / candidate

    return candidate.resolve()


def check_bats_available():
    """Check if the bats binary is available on PATH."""
    try:
        subprocess.run(
            ["bats", "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def run_bats(bats_file, log):
    """
    Run bats on a single bats file.

    Args:
        bats_file: Path to the .bats file to run
        log: Logger instance

    Returns:
        True if the tests passed, False otherwise.
    """
    log.info(f"Running bats: {bats_file}")
    result = subprocess.run(["bats", "--pretty", "--timing", str(bats_file)])
    if result.returncode == 0:
        log.debug(f"✓ bats passed for: {bats_file}")
        return True
    log.error(f"✗ bats failed for: {bats_file}")
    return False


def main():
    """Main function."""
    args = parse_args()
    log = get_logger(args.debug)

    log.debug(f"Arguments: {args}")

    if not check_bats_available():
        log.error("bats is not available on PATH")
        log.error("Please install bats-core: https://github.com/bats-core/bats-core")
        return 1

    # If no files are provided, exit successfully.
    if not args.files:
        log.info("No files provided, nothing to check")
        return 0

    root = Path.cwd()
    log.debug(f"Root: {root}")

    seen = set()
    bats_files = []

    for file_path in args.files:
        sh_path = Path(file_path)
        if sh_path.suffix != ".sh":
            log.debug(f"Skipping non-.sh file: {sh_path}")
            continue

        bats_path = resolve_pattern(args.pattern, sh_path, root)
        log.debug(f"Resolved {sh_path} -> {bats_path}")

        if not bats_path.is_file():
            log.debug(f"No companion bats file at: {bats_path}")
            continue

        if bats_path in seen:
            log.debug(f"Already queued: {bats_path}")
            continue

        seen.add(bats_path)
        bats_files.append(bats_path)

    if not bats_files:
        log.info("No bats companion files found for the given scripts")
        return 0

    failed = []
    for bats_file in bats_files:
        if not run_bats(bats_file, log):
            failed.append(bats_file)

    if failed:
        log.error(f"{len(failed)} of {len(bats_files)} bats file(s) failed:")
        for bats_file in failed:
            log.error(f"  - {bats_file}")
        return 1

    log.info(f"All {len(bats_files)} bats file(s) passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
