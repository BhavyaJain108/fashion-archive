import pytest

from backend.archive.browser.stealth import STEALTH_JS, STEALTH_USER_AGENT, stealth_args


@pytest.mark.unit
def test_stealth_js_patches_key_vectors():
    for marker in ("navigator", "plugins", "AutomationControlled".lower() and "cdc_", "languages"):
        assert marker in STEALTH_JS
    # It must NOT re-patch webdriver in JS (that backfires — the launch flag handles it).
    assert "navigator.webdriver" not in STEALTH_JS


@pytest.mark.unit
def test_launch_args_include_the_load_bearing_flag():
    assert "--disable-blink-features=AutomationControlled" in stealth_args()


@pytest.mark.unit
def test_user_agent_is_a_real_chrome_string():
    assert STEALTH_USER_AGENT.startswith("Mozilla/5.0") and "Chrome/" in STEALTH_USER_AGENT
