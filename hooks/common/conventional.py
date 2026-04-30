import re

# Conventional Commits type -> semver portion to bump.
# Aligned with semantic-release defaults; other valid CC types (chore, docs,
# style, refactor, revert, test, build, ci, ...) parse correctly but do not
# trigger a version bump.
TYPE_TO_PORTION = {
    "feat": "minor",
    "fix": "patch",
    "perf": "patch",
}

# Higher number means bigger bump
PORTION_RANK = {
    "patch": 1,
    "minor": 2,
    "major": 3,
}

HEADER_RE = re.compile(
    r"^(?P<type>[a-zA-Z]+)"
    r"(?:\((?P<scope>[^)]+)\))?"
    r"(?P<bang>!)?"
    r": (?P<description>.+)$"
)

BREAKING_FOOTER_RE = re.compile(r"^BREAKING[ -]CHANGE: ", re.MULTILINE)


def parse_commit(message):
    """Parse a Conventional Commits message.

    Returns a dict with keys: type, scope, breaking, description.
    Returns None if the message does not match the spec.
    """
    if message is None:
        return None

    stripped = message.lstrip("\n").rstrip()

    if not stripped:
        return None

    header, _, body = stripped.partition("\n")

    match = HEADER_RE.match(header.strip())

    if match is None:
        return None

    breaking = bool(match.group("bang")) or bool(BREAKING_FOOTER_RE.search(body))

    return {
        "type": match.group("type").lower(),
        "scope": match.group("scope"),
        "breaking": breaking,
        "description": match.group("description"),
    }


def portion_for_commit(parsed):
    """Return the semver portion for a parsed commit, or None."""
    if parsed is None:
        return None

    if parsed["breaking"]:
        return "major"

    return TYPE_TO_PORTION.get(parsed["type"])


def bump_from_messages(messages):
    """Determine the highest semver portion to bump from a list of messages.

    Returns a tuple ``(portion, has_valid_cc)`` where:
      - ``portion`` is 'major', 'minor', 'patch', or None when no message
        carries a bump-eligible type.
      - ``has_valid_cc`` is True if at least one message parses as a valid
        Conventional Commits message (regardless of whether it bumps).
    """
    highest = None
    highest_rank = 0
    has_valid_cc = False

    for msg in messages:
        parsed = parse_commit(msg)

        if parsed is None:
            continue

        has_valid_cc = True

        portion = portion_for_commit(parsed)

        if portion is None:
            continue

        rank = PORTION_RANK[portion]

        if rank > highest_rank:
            highest = portion
            highest_rank = rank

    return highest, has_valid_cc
