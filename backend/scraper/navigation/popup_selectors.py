"""
Shared popup/modal selectors used by both async (navigation) and sync (URL extraction) code.

Keep selectors centralized here for consistency across the pipeline.
"""

# Popup close button selectors - ordered by priority
POPUP_CLOSE_SELECTORS = [
    # Cookie consent
    'button:has-text("Accept All Cookies")',
    'button:has-text("Accept All")',
    'button:has-text("ACCEPT ALL COOKIES")',
    'button:has-text("Allow All")',
    'button:has-text("Accept Cookies")',
    '[id*="cookie"] button:has-text("Accept")',
    '[id*="consent"] button:has-text("Accept")',
    # Geolocation/country popups
    '#popin-ip',
    '.popin__geoloc a[data-locale="en_US"]',
    '.js-close-panel[data-panel-id*="geoloc"]',
    # Newsletter/signup close buttons
    '#attentive_overlay button[aria-label*="close" i]',
    '#attentive_overlay button:has-text("Close")',
    '[class*="newsletter"] button[aria-label*="close" i]',
    '[class*="popup"] button[aria-label*="close" i]',
    '[class*="modal"] button[aria-label*="close" i]',
    # Klaviyo popups
    '[data-testid*="klaviyo"] button[aria-label*="close" i]',
    '[class*="klaviyo"] button[aria-label*="close" i]',
    '[class*="klaviyo"] button:has-text("Close")',
    '[class*="klaviyo"] button:has-text("No thanks")',
    'form[data-testid*="klaviyo"] button[aria-label*="close" i]',
    'button[aria-label="Close dialog"]',
    'button[aria-label="Close form"]',
    # Promo/discount popups
    '[class*="promo"] button:has-text("Close")',
    '[class*="promo"] button:has-text("No thanks")',
    '[class*="discount"] button:has-text("Close")',
    '[class*="offer"] button:has-text("Close")',
    'button:has-text("No thanks")',
    'button:has-text("Maybe later")',
    'button:has-text("Continue without")',
    # Spin wheel / gamification
    '[class*="wheel"] button:has-text("Close")',
    '[class*="spin"] button:has-text("Close")',
    # Generic close buttons on overlays
    '[class*="overlay"] button:has-text("Close")',
    '[class*="overlay"] button[aria-label*="close" i]',
]

# Iframe selectors to remove
POPUP_IFRAME_SELECTORS = [
    'iframe[title*="Sign Up"]',
    'iframe[title*="Newsletter"]',
    'iframe[title*="Popup"]',
]

# Overlay elements to remove from DOM entirely
OVERLAY_REMOVAL_SELECTORS = [
    '[aria-label="POPUP Form"]',
    'div.kl-private-reset-css-Xuajs1[role="dialog"]',
    '#attentive_overlay',
]
