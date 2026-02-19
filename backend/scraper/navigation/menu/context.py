"""
Menu context for tracking menu state.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class MenuContext:
    """
    Holds menu state to verify menu stays open after interactions.

    Only created when a menu was successfully opened. Pass to click/hover
    functions to automatically check and restore menu state after interaction.
    """
    before_aria: str          # ARIA snapshot before menu was opened
    base_url: str             # URL to return to if we navigate away
    menu_start_line: str      # First new line when menu opened (for quick check)
    boundary_marker: str = None  # First landmark after menu (e.g., "- banner:") to truncate ARIA

    @classmethod
    def from_menu_result(cls, result: dict, base_url: str) -> Optional['MenuContext']:
        """Create MenuContext from open_menu_and_capture() result."""
        if not result.get('opened'):
            return None

        menu_start = result.get('menu_start')
        menu_start_line = menu_start[1] if menu_start else None
        boundary_marker = result.get('boundary_marker')

        return cls(
            before_aria=result['before_aria'],
            base_url=base_url,
            menu_start_line=menu_start_line,
            boundary_marker=boundary_marker
        )
