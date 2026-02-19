"""
ARIA snapshot diffing utilities.

Compare before/after ARIA snapshots to detect menu changes,
new content revealed by interactions, etc.
"""


def get_new_content(aria_before: str, aria_after: str) -> str:
    """
    Extract only NEW lines that appeared after an interaction.
    Returns the diff as a string - only content that wasn't there before.
    """
    before_lines = set(aria_before.split('\n'))
    after_lines = aria_after.split('\n')

    # Keep only lines that weren't there before
    new_lines = [line for line in after_lines if line not in before_lines]
    return '\n'.join(new_lines)


def diff_aria_states(before: str, after: str) -> tuple[int, list[str]] | None:
    """
    Compare ARIA before and after menu opens.
    Returns (first_new_line_index, new_lines) or None if no diff.

    The menu content is the new/changed content that appeared after opening.
    """
    before_lines = before.split('\n')
    after_lines = after.split('\n')

    before_set = set(before_lines)

    # Find first line in 'after' that wasn't in 'before'
    first_new_idx = None
    new_lines = []

    for i, line in enumerate(after_lines):
        if line not in before_set:
            if first_new_idx is None:
                first_new_idx = i
            new_lines.append(line)

    if first_new_idx is None:
        return None

    return (first_new_idx, new_lines)


def find_menu_start(before: str, after: str) -> tuple[int, str] | None:
    """
    Find where the menu content starts by comparing before/after ARIA states.
    Returns (line_index, first_new_line) or None if no change detected.
    """
    result = diff_aria_states(before, after)
    if result is None:
        return None

    first_idx, new_lines = result
    first_line = new_lines[0] if new_lines else ""
    return (first_idx, first_line.strip()[:100])


def extract_menu_aria(before: str, after: str, context_lines: int = 3) -> str:
    """
    Extract just the menu portion of ARIA by comparing before/after states.
    Keeps a few lines before the first new content for context.

    Args:
        before: ARIA snapshot before opening menu
        after: ARIA snapshot after opening menu
        context_lines: Number of lines to keep before new content

    Returns:
        Truncated ARIA with just menu content, or full 'after' if no diff found
    """
    result = find_menu_start(before, after)

    if result is None:
        return after

    menu_start, _ = result
    lines = after.split('\n')
    start_line = max(0, menu_start - context_lines)

    return '\n'.join(lines[start_line:])


def is_menu_still_open(current_aria: str, menu_start_line: str) -> bool:
    """
    Check if menu is still open by looking for the first new line from menu opening.

    Args:
        current_aria: Current ARIA snapshot
        menu_start_line: The first new line that appeared when menu opened

    Returns True if that line is still present (menu still open).
    """
    if not menu_start_line:
        return True  # Can't verify, assume open

    return menu_start_line in current_aria


def hover_revealed_content(aria_before: str, aria_after: str) -> tuple[bool, str]:
    """
    Check if hover revealed NEW content (links, buttons, menuitems, etc).

    Uses line-based diff to detect any new navigation content.
    Counts new lines containing interactive elements.

    Returns (revealed: bool, reason: str)
    """
    before_lines = set(aria_before.split('\n'))
    after_lines = aria_after.split('\n')

    # Find NEW lines that appeared
    new_lines = [line for line in after_lines if line not in before_lines]

    if not new_lines:
        return False, "no new content"

    # Count lines with interactive elements (links, buttons, menuitems, tabs)
    interactive_keywords = ['link', 'button', 'menuitem', 'tab']
    interactive_count = sum(
        1 for line in new_lines
        if any(kw in line.lower() for kw in interactive_keywords)
    )

    # Require at least 3 new interactive elements to count as "revealed"
    # (avoids false positives from tooltips/popups)
    if interactive_count >= 3:
        return True, f"new content (+{interactive_count} interactive elements)"

    # Also check for significant content even without interactive keywords
    # (some menus use generic elements)
    if len(new_lines) >= 10:
        return True, f"new content (+{len(new_lines)} lines)"

    return False, f"minimal change (+{len(new_lines)} lines, {interactive_count} interactive)"


def count_interactive_elements(text: str) -> int:
    """
    Count interactive elements (links, buttons, menuitems, tabs) in ARIA text.
    """
    interactive_keywords = ['link', 'button', 'menuitem', 'tab']
    return sum(
        1 for line in text.split('\n')
        if any(kw in line.lower() for kw in interactive_keywords)
    )


def get_content_diff(aria_before: str, aria_after: str) -> dict:
    """
    Get both positive (added) and negative (removed) content changes.

    Returns dict with:
        - added: str - lines that appeared
        - removed: str - lines that disappeared
        - added_count: int - number of interactive elements added
        - removed_count: int - number of interactive elements removed
        - is_replacement: bool - True if content was replaced (submenu navigation)
    """
    before_lines = set(aria_before.split('\n'))
    after_lines = set(aria_after.split('\n'))

    added = [line for line in after_lines if line not in before_lines]
    removed = [line for line in before_lines if line not in after_lines]

    def count_interactive(lines):
        return sum(
            1 for line in lines
            if any(kw in line.lower() for kw in ['link', 'button', 'menuitem', 'tab'])
        )

    added_count = count_interactive(added)
    removed_count = count_interactive(removed)

    # Content replacement: significant elements both added AND removed
    is_replacement = added_count >= 3 and removed_count >= 3

    return {
        'added': '\n'.join(added),
        'removed': '\n'.join(removed),
        'added_count': added_count,
        'removed_count': removed_count,
        'is_replacement': is_replacement
    }
