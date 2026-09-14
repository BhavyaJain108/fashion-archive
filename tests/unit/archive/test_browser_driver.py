"""Which browser the T2 lane drives, and what gets injected into it."""

import pytest

from backend.archive.browser.stealth import STEALTH_JS
from backend.archive.browser.transport import PlaywrightTransport, stealth_scripts
from backend.archive.domain.brand import TransportLevel


@pytest.mark.unit
def test_plain_playwright_needs_the_hand_rolled_patches():
    assert stealth_scripts("playwright") == [STEALTH_JS]


@pytest.mark.unit
def test_patchright_must_not_be_given_the_hand_rolled_patches():
    """Patchright removes the automation traces at the CDP layer. Injecting our
    Object.defineProperty patches on top puts back exactly what it stripped: a property
    whose getter does not read as native is itself the detection signal."""
    assert stealth_scripts("patchright") == []


@pytest.mark.unit
def test_the_default_driver_is_unchanged():
    t = PlaywrightTransport()
    assert t.driver == "playwright"
    assert t.level is TransportLevel.T2


@pytest.mark.unit
def test_an_unknown_driver_is_refused_at_construction():
    """Better here than as an ImportError thirty seconds into a sweep."""
    with pytest.raises(ValueError) as e:
        PlaywrightTransport(driver="chromedriver")
    assert "chromedriver" in str(e.value)
