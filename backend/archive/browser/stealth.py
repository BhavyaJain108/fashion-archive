"""Stealth patches for Playwright — self-contained copy (no legacy imports; spec rule).

Ported verbatim from backend/prod_page_v2/stealth/patches.py so the archive body stands
alone. Patches the detection vectors Cloudflare & friends check when a headless browser loads.
"""

# Injected before every page load. NB: webdriver is handled by the launch flag, not JS —
# re-patching it in JS re-adds the property and makes detection *easier*.
STEALTH_JS = """
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [
            {name: 'Chrome PDF Plugin', description: 'Portable Document Format',
             filename: 'internal-pdf-viewer', length: 1},
            {name: 'Chrome PDF Viewer', description: '',
             filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', length: 1},
            {name: 'Native Client', description: '', filename: 'internal-nacl-plugin', length: 2}
        ];
        plugins.item = (i) => plugins[i] || null;
        plugins.namedItem = (n) => plugins.find(p => p.name === n) || null;
        plugins.refresh = () => {};
        return plugins;
    },
    configurable: true
});

window.chrome = {
    app: {isInstalled: false},
    runtime: {connect: () => {}, sendMessage: () => {}, id: undefined},
    csi: () => {},
    loadTimes: () => ({})
};

const originalQuery = navigator.permissions.query.bind(navigator.permissions);
navigator.permissions.query = (p) =>
    p && p.name === 'notifications'
        ? Promise.resolve({state: Notification.permission, onchange: null})
        : originalQuery(p);

Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en'], configurable: true});
Object.defineProperty(navigator, 'deviceMemory', {get: () => 8, configurable: true});

const automationProps = ['__webdriver_evaluate','__selenium_evaluate','__webdriver_script_function',
    '__driver_evaluate','__webdriver_unwrapped','__fxdriver_evaluate','__driver_unwrapped',
    'callSelenium','_selenium','callPhantom','_phantom','phantom','__nightmare'];
for (const prop of automationProps) { delete window[prop]; delete document[prop]; }
for (const prop of Object.keys(window).filter(k => k.startsWith('cdc_'))) { delete window[prop]; }

if (window.outerWidth === window.innerWidth) {
    Object.defineProperty(window, 'outerWidth', {get: () => window.innerWidth + 10, configurable: true});
    Object.defineProperty(window, 'outerHeight', {get: () => window.innerHeight + 85, configurable: true});
}
"""


def stealth_args() -> list[str]:
    """Chrome launch flags that reduce automation fingerprints."""
    return [
        "--disable-blink-features=AutomationControlled",  # removes the webdriver trace
        "--disable-dev-shm-usage",
        "--disable-infobars",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-popup-blocking",
        "--no-first-run",
        "--password-store=basic",
        "--use-mock-keychain",
        "--force-color-profile=srgb",
        "--disable-automation",
    ]


STEALTH_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
