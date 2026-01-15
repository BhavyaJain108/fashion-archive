"""
Page waiting utilities for reliable scraping.
Handles dynamic content loading across different site speeds.

Usage:
    from backend.utils.page_wait import wait_for_page_ready

    await page.goto(url)
    await wait_for_page_ready(page)
"""

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout


async def wait_for_page_ready(
    page: Page,
    timeout: int = 5000,
    min_wait: int = 500,
    network_idle: bool = True
) -> None:
    """
    Wait for page to be ready for interaction.

    Uses network idle detection with a timeout, plus a minimum wait
    for animations. Fast sites finish quickly, slow sites are capped.

    Args:
        page: Playwright page object
        timeout: Max time to wait for network idle (ms)
        min_wait: Minimum wait time for animations (ms)
        network_idle: Whether to wait for network idle
    """
    if network_idle:
        try:
            await page.wait_for_load_state("networkidle", timeout=timeout)
        except PlaywrightTimeout:
            # Timeout is ok - site might have constant polling
            pass

    # Always wait minimum time for CSS animations/transitions
    if min_wait > 0:
        await page.wait_for_timeout(min_wait)


async def wait_for_stable_content(
    page: Page,
    selector: str = 'body',
    interval: int = 300,
    stable_checks: int = 2,
    timeout: int = 5000
) -> bool:
    """
    Wait until element content stops changing.

    Useful for dynamic content that loads progressively.
    Checks if the element's text/structure is stable across
    multiple checks.

    Args:
        page: Playwright page object
        selector: CSS selector for element to monitor
        interval: Time between stability checks (ms)
        stable_checks: Number of consecutive stable checks required
        timeout: Max total time to wait (ms)

    Returns:
        True if content stabilized, False if timeout
    """
    prev_content = None
    stable = 0
    elapsed = 0

    while stable < stable_checks and elapsed < timeout:
        try:
            element = page.locator(selector)
            content = await element.inner_text()
        except Exception:
            content = None

        if content == prev_content:
            stable += 1
        else:
            stable = 0
            prev_content = content

        await page.wait_for_timeout(interval)
        elapsed += interval

    return stable >= stable_checks


async def wait_for_stable_aria(
    page: Page,
    interval: int = 300,
    stable_checks: int = 2,
    timeout: int = 5000
) -> bool:
    """
    Wait until ARIA snapshot stops changing.

    More thorough than wait_for_stable_content - checks the full
    accessibility tree. Good for navigation menus that load dynamically.

    Args:
        page: Playwright page object
        interval: Time between stability checks (ms)
        stable_checks: Number of consecutive stable checks required
        timeout: Max total time to wait (ms)

    Returns:
        True if ARIA stabilized, False if timeout
    """
    prev_aria = None
    stable = 0
    elapsed = 0

    while stable < stable_checks and elapsed < timeout:
        try:
            aria = await page.locator('body').aria_snapshot()
        except Exception:
            aria = None

        if aria == prev_aria:
            stable += 1
        else:
            stable = 0
            prev_aria = aria

        await page.wait_for_timeout(interval)
        elapsed += interval

    return stable >= stable_checks


async def wait_for_element(
    page: Page,
    selector: str,
    timeout: int = 5000,
    visible: bool = True
) -> bool:
    """
    Wait for element to appear (and optionally be visible).

    Args:
        page: Playwright page object
        selector: CSS selector for element
        timeout: Max time to wait (ms)
        visible: Whether element must be visible (not just in DOM)

    Returns:
        True if element found, False if timeout
    """
    try:
        locator = page.locator(selector)
        if visible:
            await locator.wait_for(state="visible", timeout=timeout)
        else:
            await locator.wait_for(state="attached", timeout=timeout)
        return True
    except PlaywrightTimeout:
        return False


async def wait_for_navigation_ready(
    page: Page,
    timeout: int = 5000,
    min_wait: int = 500
) -> None:
    """
    Wait for navigation elements to be ready.

    Specialized wait for scraping navigation menus. Waits for
    network idle then checks for common nav element roles.

    Args:
        page: Playwright page object
        timeout: Max time for network idle (ms)
        min_wait: Minimum wait for animations (ms)
    """
    await wait_for_page_ready(page, timeout=timeout, min_wait=0)

    # Try to wait for navigation elements
    nav_selectors = [
        '[role="navigation"]',
        '[role="menubar"]',
        'nav',
        'header [role="tab"]',
        'header [role="button"]'
    ]

    for selector in nav_selectors:
        try:
            locator = page.locator(selector)
            if await locator.count() > 0:
                await locator.first.wait_for(state="visible", timeout=1000)
                break
        except Exception:
            continue

    # Minimum wait for animations
    if min_wait > 0:
        await page.wait_for_timeout(min_wait)
