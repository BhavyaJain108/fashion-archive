"""
Stealth Patches for Playwright

Patches common detection vectors to make headless Chrome look like a real browser.
Based on understanding of what Cloudflare and similar services check.
"""

# JavaScript to inject before page load that patches detection vectors
STEALTH_JS = """
// 1. Webdriver is handled by --disable-blink-features=AutomationControlled
// DO NOT patch it with JS - that re-adds the property and makes detection easier!

// 2. Mock plugins array (real Chrome has these)
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [
            {
                name: 'Chrome PDF Plugin',
                description: 'Portable Document Format',
                filename: 'internal-pdf-viewer',
                length: 1,
                0: { type: 'application/x-google-chrome-pdf', suffixes: 'pdf', description: 'Portable Document Format' }
            },
            {
                name: 'Chrome PDF Viewer',
                description: '',
                filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai',
                length: 1,
                0: { type: 'application/pdf', suffixes: 'pdf', description: '' }
            },
            {
                name: 'Native Client',
                description: '',
                filename: 'internal-nacl-plugin',
                length: 2,
                0: { type: 'application/x-nacl', suffixes: '', description: 'Native Client Executable' },
                1: { type: 'application/x-pnacl', suffixes: '', description: 'Portable Native Client Executable' }
            }
        ];

        // Make it array-like
        plugins.item = (index) => plugins[index] || null;
        plugins.namedItem = (name) => plugins.find(p => p.name === name) || null;
        plugins.refresh = () => {};

        return plugins;
    },
    configurable: true
});

// 3. Mock mimeTypes
Object.defineProperty(navigator, 'mimeTypes', {
    get: () => {
        const mimeTypes = [
            { type: 'application/pdf', suffixes: 'pdf', description: '', enabledPlugin: navigator.plugins[1] },
            { type: 'application/x-google-chrome-pdf', suffixes: 'pdf', description: 'Portable Document Format', enabledPlugin: navigator.plugins[0] },
            { type: 'application/x-nacl', suffixes: '', description: 'Native Client Executable', enabledPlugin: navigator.plugins[2] },
            { type: 'application/x-pnacl', suffixes: '', description: 'Portable Native Client Executable', enabledPlugin: navigator.plugins[2] }
        ];

        mimeTypes.item = (index) => mimeTypes[index] || null;
        mimeTypes.namedItem = (name) => mimeTypes.find(m => m.type === name) || null;

        return mimeTypes;
    },
    configurable: true
});

// 4. Mock chrome object
window.chrome = {
    app: {
        isInstalled: false,
        InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
        RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }
    },
    runtime: {
        OnInstalledReason: { CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' },
        OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' },
        PlatformArch: { ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
        PlatformNaclArch: { ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
        PlatformOs: { ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win' },
        RequestUpdateCheckStatus: { NO_UPDATE: 'no_update', THROTTLED: 'throttled', UPDATE_AVAILABLE: 'update_available' },
        connect: () => {},
        sendMessage: () => {},
        id: undefined
    },
    csi: () => {},
    loadTimes: () => ({
        commitLoadTime: Date.now() / 1000,
        connectionInfo: 'http/1.1',
        finishDocumentLoadTime: Date.now() / 1000,
        finishLoadTime: Date.now() / 1000,
        firstPaintAfterLoadTime: 0,
        firstPaintTime: Date.now() / 1000,
        navigationType: 'Other',
        npnNegotiatedProtocol: 'unknown',
        requestTime: Date.now() / 1000,
        startLoadTime: Date.now() / 1000,
        wasAlternateProtocolAvailable: false,
        wasFetchedViaSpdy: false,
        wasNpnNegotiated: false
    })
};

// 5. Fix permissions API behavior
const originalQuery = navigator.permissions.query.bind(navigator.permissions);
navigator.permissions.query = (parameters) => {
    if (parameters.name === 'notifications') {
        return Promise.resolve({ state: Notification.permission, onchange: null });
    }
    return originalQuery(parameters);
};

// 6. Mock languages (make sure it looks normal)
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
    configurable: true
});

// 7. Mock deviceMemory (headless often has undefined)
Object.defineProperty(navigator, 'deviceMemory', {
    get: () => 8,
    configurable: true
});

// 8. Fix WebGL vendor/renderer (harder to fix completely, but we can try)
const getParameterProxyHandler = {
    apply: function(target, thisArg, args) {
        const param = args[0];
        const result = Reflect.apply(target, thisArg, args);

        // UNMASKED_VENDOR_WEBGL
        if (param === 37445) {
            return 'Intel Inc.';
        }
        // UNMASKED_RENDERER_WEBGL
        if (param === 37446) {
            return 'Intel Iris OpenGL Engine';
        }
        return result;
    }
};

try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
    if (gl) {
        const originalGetParameter = gl.getParameter.bind(gl);
        gl.getParameter = new Proxy(originalGetParameter, getParameterProxyHandler);

        // Also patch for webgl2
        const gl2 = canvas.getContext('webgl2');
        if (gl2) {
            const originalGetParameter2 = gl2.getParameter.bind(gl2);
            gl2.getParameter = new Proxy(originalGetParameter2, getParameterProxyHandler);
        }
    }
} catch (e) {}

// 9. Remove automation-related properties from window
const automationProps = ['__webdriver_evaluate', '__selenium_evaluate', '__webdriver_script_function',
                         '__webdriver_script_func', '__webdriver_script_fn', '__fxdriver_evaluate',
                         '__driver_unwrapped', '__webdriver_unwrapped', '__driver_evaluate',
                         '__selenium_unwrapped', '__fxdriver_unwrapped', 'callSelenium',
                         '_selenium', 'callPhantom', '_phantom', 'phantom', '__nightmare'];

for (const prop of automationProps) {
    delete window[prop];
    delete document[prop];
}

// 10. Remove CDP (Chrome DevTools Protocol) artifacts
// These are added by Playwright/Puppeteer
const cdcProps = Object.keys(window).filter(k => k.startsWith('cdc_'));
for (const prop of cdcProps) {
    delete window[prop];
}

// 11. Fix outerWidth/outerHeight (headless has same as inner)
if (window.outerWidth === window.innerWidth && window.outerHeight === window.innerHeight) {
    Object.defineProperty(window, 'outerWidth', {
        get: () => window.innerWidth + 10,
        configurable: true
    });
    Object.defineProperty(window, 'outerHeight', {
        get: () => window.innerHeight + 85,  // Chrome toolbar height
        configurable: true
    });
}

console.log('[Stealth] Patches applied');
"""


def get_stealth_args():
    """Get Chrome launch arguments that help avoid detection."""
    return [
        '--disable-blink-features=AutomationControlled',  # Key: removes webdriver traces
        '--disable-features=IsolateOrigins,site-per-process',
        '--disable-infobars',
        '--disable-background-networking',
        '--disable-background-timer-throttling',
        '--disable-backgrounding-occluded-windows',
        '--disable-breakpad',
        '--disable-component-extensions-with-background-pages',
        '--disable-component-update',
        '--disable-default-apps',
        '--disable-dev-shm-usage',
        '--disable-extensions',
        '--disable-features=TranslateUI',
        '--disable-hang-monitor',
        '--disable-ipc-flooding-protection',
        '--disable-popup-blocking',
        '--disable-prompt-on-repost',
        '--disable-renderer-backgrounding',
        '--disable-sync',
        '--enable-features=NetworkService,NetworkServiceInProcess',
        '--force-color-profile=srgb',
        '--metrics-recording-only',
        '--no-first-run',
        '--password-store=basic',
        '--use-mock-keychain',
        '--export-tagged-pdf',
        # Disable automation flags
        '--disable-automation',
        '--disable-blink-features=AutomationControlled',
    ]


def get_stealth_user_agent():
    """Get a realistic user agent string."""
    return (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )
