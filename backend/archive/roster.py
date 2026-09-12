"""Which shops the archive follows, and which of those the app shows.

brands.yml is the roster itself. The CLI and the daemon read every line of it; the app
reads the subset marked small or mid. Nothing in the app can add to it — a brand joins
the archive by being written into that file, which is the only place the decision is
recorded and the only place to change it.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

BRANDS_YML = Path(__file__).parent / "brands.yml"

# The sizes the app shows. large houses run enterprise bot defences and are not what this
# archive is for; a multi_brand outlet sells other labels, so its `brand` column stops
# naming one brand and every per-brand measurement stops meaning anything.
APP_SIZES = ("small", "mid")


@dataclass(frozen=True)
class RosterEntry:
    domain: str
    homepage_url: str
    display_name: str | None = None
    notes: str | None = None
    size: str = "small"

    @property
    def name(self) -> str:
        return self.display_name or self.domain.removeprefix("www.").split(".")[0]


def load_roster(path: Path | None = None) -> list[RosterEntry]:
    data = yaml.safe_load((path or BRANDS_YML).read_text()) or {}
    return [
        RosterEntry(
            domain=b["domain"],
            homepage_url=b["homepage_url"],
            display_name=b.get("display_name"),
            notes=b.get("notes"),
            size=b.get("size", "small"),
        )
        for b in data.get("brands", [])
    ]


def app_roster(path: Path | None = None, sizes: tuple[str, ...] = APP_SIZES) -> list[RosterEntry]:
    """The roster the My Brands page shows, in display-name order."""
    return sorted(
        (e for e in load_roster(path) if e.size in sizes),
        key=lambda e: e.name.lower(),
    )
