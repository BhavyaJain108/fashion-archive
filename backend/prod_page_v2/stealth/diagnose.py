"""
Bot Detection Diagnostic Tool

Checks what signals our headless browser is leaking that could be used
to detect automation. Understanding detection is key to evasion.
"""

import asyncio
import json
from playwright.async_api import async_playwright


# JavaScript to check common detection vectors
DETECTION_CHECKS = """
() => {
    const results = {
        // 1. WebDriver Detection
        webdriver: {
            navigator_webdriver: navigator.webdriver,
            webdriver_in_navigator: 'webdriver' in navigator,
            // Chrome-specific
            domAutomation: window.domAutomation,
            domAutomationController: window.domAutomationController,
        },

        // 2. User Agent Analysis
        userAgent: {
            full: navigator.userAgent,
            hasHeadless: navigator.userAgent.includes('HeadlessChrome'),
            hasAutomation: navigator.userAgent.includes('Automation'),
        },

        // 3. Navigator Properties
        navigator: {
            platform: navigator.platform,
            languages: navigator.languages,
            language: navigator.language,
            hardwareConcurrency: navigator.hardwareConcurrency,
            deviceMemory: navigator.deviceMemory,
            maxTouchPoints: navigator.maxTouchPoints,
            vendor: navigator.vendor,
            webdriver: navigator.webdriver,
        },

        // 4. Plugins (headless often has none)
        plugins: {
            count: navigator.plugins.length,
            list: Array.from(navigator.plugins).map(p => p.name),
        },

        // 5. Chrome Object (should exist in real Chrome)
        chrome: {
            exists: typeof window.chrome !== 'undefined',
            hasRuntime: typeof window.chrome?.runtime !== 'undefined',
            hasApp: typeof window.chrome?.app !== 'undefined',
            csi: typeof window.chrome?.csi !== 'undefined',
            loadTimes: typeof window.chrome?.loadTimes !== 'undefined',
        },

        // 6. Permissions API Behavior
        permissions: {
            available: typeof navigator.permissions !== 'undefined',
        },

        // 7. WebGL Renderer (can reveal headless)
        webgl: {},

        // 8. Screen Properties
        screen: {
            width: screen.width,
            height: screen.height,
            availWidth: screen.availWidth,
            availHeight: screen.availHeight,
            colorDepth: screen.colorDepth,
            pixelDepth: screen.pixelDepth,
            // Headless often has 0,0 for outer dimensions
            outerWidth: window.outerWidth,
            outerHeight: window.outerHeight,
        },

        // 9. Timing/Performance
        timing: {
            // Headless often has suspicious timing
            connectionStart: performance.timing?.connectStart,
            // Check if dates are consistent
            dateNow: Date.now(),
            performanceNow: performance.now(),
        },

        // 10. Browser Features
        features: {
            notifications: typeof Notification !== 'undefined',
            bluetooth: typeof navigator.bluetooth !== 'undefined',
            usb: typeof navigator.usb !== 'undefined',
            serial: typeof navigator.serial !== 'undefined',
            mediaDevices: typeof navigator.mediaDevices !== 'undefined',
        },

        // 11. Automation-specific globals
        automation: {
            phantom: typeof window.callPhantom !== 'undefined' || typeof window._phantom !== 'undefined',
            nightmare: typeof window.__nightmare !== 'undefined',
            selenium: typeof window.document.__selenium_unwrapped !== 'undefined' ||
                      typeof window.document.__webdriver_evaluate !== 'undefined' ||
                      typeof window.document.__driver_evaluate !== 'undefined',
            webdriver_keys: Object.keys(window).filter(k => k.includes('webdriver') || k.includes('selenium') || k.includes('driver')),
            cdc: Object.keys(window).filter(k => k.startsWith('cdc_')),
        },

        // 12. iFrame detection
        iframe: {
            isIframe: window.self !== window.top,
        },
    };

    // WebGL check (separate try-catch)
    try {
        const canvas = document.createElement('canvas');
        const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
        if (gl) {
            const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
            if (debugInfo) {
                results.webgl.vendor = gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL);
                results.webgl.renderer = gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL);
                results.webgl.hasSwiftShader = results.webgl.renderer?.includes('SwiftShader');
            }
        }
    } catch (e) {
        results.webgl.error = e.message;
    }

    // Permissions check (separate try-catch)
    try {
        if (navigator.permissions) {
            results.permissions.query_available = typeof navigator.permissions.query === 'function';
        }
    } catch (e) {
        results.permissions.error = e.message;
    }

    return results;
}
"""


async def diagnose_detection(url: str = "https://www.aritzia.com"):
    """Run detection diagnostics and report what's exposing us."""

    print("=" * 60)
    print("BOT DETECTION DIAGNOSTIC")
    print("=" * 60)

    async with async_playwright() as p:
        # Launch with default settings (what we currently use)
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Run detection checks
        print("\n[1] Running detection checks...")
        results = await page.evaluate(DETECTION_CHECKS)

        # Analyze and report
        print("\n" + "=" * 60)
        print("DETECTION VECTORS FOUND")
        print("=" * 60)

        issues = []
        warnings = []

        # Check WebDriver
        if results['webdriver']['navigator_webdriver']:
            issues.append("🚨 navigator.webdriver = true (CRITICAL)")

        # Check User Agent
        if results['userAgent']['hasHeadless']:
            issues.append("🚨 User-Agent contains 'HeadlessChrome'")

        # Check Plugins
        if results['plugins']['count'] == 0:
            issues.append("🚨 No browser plugins (real browsers have plugins)")

        # Check Chrome object
        if not results['chrome']['exists']:
            issues.append("🚨 window.chrome doesn't exist")
        elif not results['chrome']['hasRuntime']:
            warnings.append("⚠️  window.chrome.runtime missing")

        # Check WebGL
        if results['webgl'].get('hasSwiftShader'):
            issues.append("🚨 WebGL using SwiftShader (headless indicator)")

        # Check screen dimensions
        if results['screen']['outerWidth'] == 0:
            issues.append("🚨 outerWidth = 0 (headless indicator)")

        # Check automation globals
        if results['automation']['cdc']:
            issues.append(f"🚨 Chrome DevTools Protocol vars exposed: {results['automation']['cdc']}")
        if results['automation']['webdriver_keys']:
            issues.append(f"🚨 WebDriver globals found: {results['automation']['webdriver_keys']}")

        # Print issues
        if issues:
            print("\n🔴 CRITICAL ISSUES (will trigger detection):")
            for issue in issues:
                print(f"   {issue}")

        if warnings:
            print("\n🟡 WARNINGS (may trigger detection):")
            for warning in warnings:
                print(f"   {warning}")

        if not issues and not warnings:
            print("\n🟢 No obvious detection vectors found")

        # Print detailed results
        print("\n" + "=" * 60)
        print("DETAILED FINGERPRINT")
        print("=" * 60)

        print(f"\n📋 Navigator:")
        print(f"   webdriver: {results['webdriver']['navigator_webdriver']}")
        print(f"   platform: {results['navigator']['platform']}")
        print(f"   languages: {results['navigator']['languages']}")
        print(f"   hardwareConcurrency: {results['navigator']['hardwareConcurrency']}")
        print(f"   deviceMemory: {results['navigator']['deviceMemory']}")

        print(f"\n📋 User Agent:")
        print(f"   {results['userAgent']['full'][:80]}...")

        print(f"\n📋 Plugins: {results['plugins']['count']}")
        for plugin in results['plugins']['list'][:3]:
            print(f"   - {plugin}")

        print(f"\n📋 Chrome Object:")
        print(f"   exists: {results['chrome']['exists']}")
        print(f"   runtime: {results['chrome']['hasRuntime']}")
        print(f"   app: {results['chrome']['hasApp']}")

        print(f"\n📋 WebGL:")
        print(f"   vendor: {results['webgl'].get('vendor', 'N/A')}")
        print(f"   renderer: {results['webgl'].get('renderer', 'N/A')}")

        print(f"\n📋 Screen:")
        print(f"   dimensions: {results['screen']['width']}x{results['screen']['height']}")
        print(f"   outer: {results['screen']['outerWidth']}x{results['screen']['outerHeight']}")

        await browser.close()

        return results, issues


async def test_on_site(url: str):
    """Test if we get blocked on a specific site."""
    print(f"\n\n{'=' * 60}")
    print(f"TESTING ON: {url}")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            response = await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            await page.wait_for_timeout(3000)

            html = await page.content()
            title = await page.title()

            print(f"\n📊 Results:")
            print(f"   Status: {response.status}")
            print(f"   Title: {title}")
            print(f"   HTML length: {len(html)}")

            # Check for common block indicators
            block_indicators = [
                ('Just a moment', 'Cloudflare challenge'),
                ('Access Denied', 'Access blocked'),
                ('Please verify', 'Verification required'),
                ('captcha', 'CAPTCHA required'),
                ('blocked', 'Explicitly blocked'),
                ('bot detected', 'Bot detection triggered'),
            ]

            for indicator, message in block_indicators:
                if indicator.lower() in html.lower() or indicator.lower() in title.lower():
                    print(f"   🚫 BLOCKED: {message}")
                    break
            else:
                if len(html) > 50000:
                    print(f"   ✅ Page loaded successfully")
                else:
                    print(f"   ⚠️  Partial load (small HTML)")

        except Exception as e:
            print(f"   ❌ Error: {e}")

        await browser.close()


if __name__ == "__main__":
    async def main():
        # Run diagnostics
        results, issues = await diagnose_detection()

        # Test on problematic sites
        await test_on_site("https://www.aritzia.com/us/en/product/the-super-puff/126464.html")
        await test_on_site("https://www.cos.com/en-us/men/menswear/coatsjackets/denim/product/denim-overshirt-dark-blue-1315149001")

        print("\n\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"\nFound {len(issues)} critical detection vectors to fix.")

    asyncio.run(main())
