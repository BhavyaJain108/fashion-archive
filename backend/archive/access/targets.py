"""Which brands are worth sweeping.

brands.yml carries a free-text note per brand, and those notes are where the failures
were written down as they were found. They are prose rather than a schema, so this reads
them for what they plainly say and nothing cleverer: a note naming a refusal, a
challenge, or a page we cannot read means the brand produces nothing today.

Password-gated brands are excluded. No transport opens a password, so sweeping them
spends requests to re-learn a fact we already have.
"""

from collections.abc import Iterable

# Words the notes use for "this brand does not work". Kept literal on purpose: the notes
# are written by hand, and a regex that tried to be clever would quietly start matching
# platform names.
_FAILING = (
    "403",
    "429",
    "challenge",
    "challenged",
    "tls-level",
    "blocked",
    "denied",
    "enterprise",
    "custom nextjs",  # reachable, unreadable — the sweep's job is to say which
    "not yet probed",
)

# A password is not a door to pick.
_GATED = ("password-gated", "password link")


def is_failing(note: str | None) -> bool:
    if not note:
        return False
    text = note.lower()
    if any(marker in text for marker in _GATED):
        return False
    return any(marker in text for marker in _FAILING)


def failing_domains(roster: Iterable) -> list[str]:
    """The brands whose notes record a failure, in roster order."""
    return [e.domain for e in roster if is_failing(e.notes)]
