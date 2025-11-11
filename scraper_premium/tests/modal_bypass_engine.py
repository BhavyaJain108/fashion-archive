"""
Modal Bypass Engine
==================

Simple automated detection and bypassing of website modals/popups using CSS injection attacks.
Uses pattern matching and stores successful attacks in brand JSON files.
"""

import json
import time
import logging
import re
from typing import List, Dict, Optional
from dataclasses import dataclass
from enum import Enum
from playwright.sync_api import Page
import os


class ModalType(Enum):
    """Types of modals that can be detected"""
    SUBSCRIPTION = "subscription"
    COOKIE_CONSENT = "cookie_consent"  
    AGE_VERIFICATION = "age_verification"
    NEWSLETTER = "newsletter"
    POPUP_AD = "popup_ad"
    LOGIN_PROMPT = "login_prompt"
    OVERLAY = "overlay"
    UNKNOWN = "unknown"


@dataclass
class DetectedModal:
    """Simple modal detection result"""
    modal_type: ModalType
    selector: str
    text_content: str


@dataclass
class AttackResult:
    """Result of testing a CSS attack"""
    css_rule: str
    success: bool
    execution_time: float


class ModalBypassEngine:
    """
    Simple modal detection and bypassing engine using CSS injection attacks.
    
    This engine:
    1. Detects modals using pattern matching on DOM elements
    2. Applies CSS attacks from known successful patterns
    3. Learns successful attacks and stores them in brand JSON files
    """
    
    def __init__(self, brand_data: Dict = None):
        """Initialize the modal bypass engine"""
        self.brand_data = brand_data or {}
        
        # Comprehensive CSS attack library
        self.css_attacks = [
            # Basic hiding attacks
            "display: none !important;",
            "visibility: hidden !important;",
            "opacity: 0 !important;",
            
            # Z-index attacks
            "z-index: -9999 !important;",
            "z-index: -1 !important;",
            
            # Position attacks
            "position: absolute !important; left: -9999px !important; top: -9999px !important;",
            "position: static !important;",
            "position: relative !important; left: -100vw !important;",
            
            # Size attacks
            "height: 0 !important; overflow: hidden !important;",
            "width: 0 !important; height: 0 !important;",
            "max-height: 0 !important; overflow: hidden !important;",
            "transform: scale(0) !important;",
            
            # Interaction attacks
            "pointer-events: none !important;",
            "user-select: none !important; pointer-events: none !important;",
            
            # Backdrop attacks (for modal backdrops)
            "background: transparent !important; backdrop-filter: none !important;",
            
            # Animation/transition attacks
            "transition: none !important; animation: none !important; opacity: 0 !important;",
            
            # Content attacks
            "font-size: 0 !important; line-height: 0 !important;",
            
            # Clip attacks
            "clip: rect(0,0,0,0) !important;",
            "clip-path: inset(100%) !important;",
            
            # Transform attacks
            "transform: translateX(-100vw) !important;",
            "transform: translateY(-100vh) !important;"
        ]
        
        # Modal detection patterns
        self.modal_patterns = {
            "subscription": ["newsletter", "subscribe", "email", "signup", "join"],
            "cookie_consent": ["cookie", "consent", "privacy", "gdpr", "tracking", "accept"],
            "age_verification": ["age", "verify", "18+", "adult", "birthday", "confirm"],
            "newsletter": ["newsletter", "updates", "news", "email"],
            "popup_ad": ["sale", "discount", "offer", "deal", "promo"],
            "login_prompt": ["login", "sign in", "account", "register"]
        }
        
        # Logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    def detect_modals(self, page: Page, url: str) -> List[DetectedModal]:
        """
        Detect all modals/overlays on the current page using pattern matching.
        
        Args:
            page: Playwright page object
            url: Current page URL for context
            
        Returns:
            List of detected modals
        """
        self.logger.info(f"Detecting modals on {url}")
        
        try:
            # Wait for page to stabilize
            page.wait_for_load_state("domcontentloaded", timeout=5000)
            time.sleep(2)  # Allow any delayed modals to appear
            
            # Find potential modal elements
            modal_elements = page.evaluate("""
                () => {
                    const potentialModals = [];
                    
                    // Look for common modal selectors
                    const commonModalSelectors = [
                        '[role="dialog"]',
                        '[role="alertdialog"]',
                        '[aria-modal="true"]',
                        '.modal', '.popup', '.overlay', '.lightbox',
                        '[data-modal]', '.cookie-banner', '.newsletter-popup',
                        '.age-gate', '.subscription-modal', '.consent-modal',
                        '.modal-backdrop', '.modal-overlay', '.backdrop',
                        '.interstitial', '.popup-overlay', '.modal-container',
                        '.dialog', '.alert', '.notification-banner',
                        '.promo-modal', '.exit-intent', '.welcome-modal',
                        '#modal', '#popup', '#overlay', '#cookie-banner',
                        '[class*="modal"]', '[class*="popup"]', '[class*="overlay"]',
                        '[id*="modal"]', '[id*="popup"]', '[id*="overlay"]'
                    ];
                    
                    // Check common modal selectors first
                    commonModalSelectors.forEach(selector => {
                        const elements = document.querySelectorAll(selector);
                        elements.forEach(el => {
                            const style = window.getComputedStyle(el);
                            if (style.display !== 'none' && style.visibility !== 'hidden') {
                                potentialModals.push({
                                    selector: selector,
                                    textContent: el.innerText ? el.innerText.substring(0, 300) : '',
                                    element: el
                                });
                            }
                        });
                    });
                    
                    // Check for high z-index fixed/absolute positioned elements
                    const allElements = document.querySelectorAll('*');
                    allElements.forEach(el => {
                        const style = window.getComputedStyle(el);
                        const zIndex = parseInt(style.zIndex) || 0;
                        const rect = el.getBoundingClientRect();
                        
                        // More aggressive detection for covering elements
                        const isCoveringElement = (
                            (style.position === 'fixed' || style.position === 'absolute') &&
                            (
                                // High z-index elements
                                zIndex > 999 ||
                                // Large covering elements (potential backdrops)
                                (zIndex > 0 && rect.width > window.innerWidth * 0.8 && rect.height > window.innerHeight * 0.8) ||
                                // Elements covering significant screen area
                                (zIndex > 0 && rect.width * rect.height > window.innerWidth * window.innerHeight * 0.5)
                            ) &&
                            style.display !== 'none' &&
                            style.visibility !== 'hidden' &&
                            el.offsetWidth > 0 && el.offsetHeight > 0
                        );
                        
                        if (isCoveringElement) {
                            // Generate more robust selector
                            let selector = el.tagName.toLowerCase();
                            if (el.id) {
                                selector += '#' + el.id;
                            } else if (el.className) {
                                const classes = el.className.split(' ').filter(c => c && c.length < 20).slice(0, 3).join('.');
                                if (classes) selector += '.' + classes;
                            } else {
                                // Fallback to nth-child if no id/class
                                const parent = el.parentElement;
                                if (parent) {
                                    const siblings = Array.from(parent.children);
                                    const index = siblings.indexOf(el) + 1;
                                    selector = parent.tagName.toLowerCase() + ' > ' + selector + ':nth-child(' + index + ')';
                                }
                            }
                            
                            potentialModals.push({
                                selector: selector,
                                textContent: el.innerText ? el.innerText.substring(0, 300) : '',
                                zIndex: zIndex,
                                size: { width: rect.width, height: rect.height },
                                position: style.position,
                                element: el
                            });
                        }
                    });
                    
                    // Also check for elements that might be blocking body interaction
                    const bodyStyle = window.getComputedStyle(document.body);
                    if (bodyStyle.overflow === 'hidden' || bodyStyle.position === 'fixed') {
                        potentialModals.push({
                            selector: 'body',
                            textContent: 'Body scroll locked - potential modal open',
                            zIndex: 0,
                            size: { width: 0, height: 0 },
                            position: bodyStyle.position,
                            element: document.body
                        });
                    }
                    
                    return potentialModals;
                }
            """)
            
            if not modal_elements:
                self.logger.info("No potential modals detected")
                return []
            
            # Classify modals using text patterns
            detected_modals = []
            for element in modal_elements:
                modal_type = self._classify_modal_by_text(element["textContent"])
                if modal_type != ModalType.UNKNOWN:
                    detected_modals.append(DetectedModal(
                        modal_type=modal_type,
                        selector=element["selector"],
                        text_content=element["textContent"]
                    ))
            
            self.logger.info(f"Detected {len(detected_modals)} confirmed modals")
            return detected_modals
            
        except Exception as e:
            self.logger.error(f"Error detecting modals: {str(e)}")
            return []

    def _classify_modal_by_text(self, text_content: str) -> ModalType:
        """Classify modal type based on text content patterns"""
        text_lower = text_content.lower()
        
        for modal_type, keywords in self.modal_patterns.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return ModalType(modal_type)
        
        return ModalType.UNKNOWN

    def bypass_modals(self, page: Page, url: str) -> Dict[str, any]:
        """
        Main method to detect and bypass all modals on a page.
        
        Args:
            page: Playwright page object
            url: Current page URL
            
        Returns:
            Dictionary with bypass results
        """
        self.logger.info(f"Starting modal bypass for {url}")
        
        results = {
            "url": url,
            "modals_detected": 0,
            "modals_bypassed": 0,
            "successful_attacks": [],
            "total_time": 0,
            "success": False
        }
        
        start_time = time.time()
        
        try:
            # Detect modals
            detected_modals = self.detect_modals(page, url)
            results["modals_detected"] = len(detected_modals)
            
            if not detected_modals:
                results["success"] = True
                results["total_time"] = time.time() - start_time
                return results
            
            # Try to bypass each modal
            for modal in detected_modals:
                self.logger.info(f"Attempting to bypass {modal.modal_type.value} modal")
                
                # Get known successful attacks first
                known_attacks = self._get_known_attacks_for_modal(modal.modal_type.value)
                all_attacks = known_attacks + self.css_attacks
                
                # Test attacks until one works
                for css_rule in all_attacks:
                    result = self._test_css_attack(page, css_rule, modal.selector)
                    
                    if result.success:
                        self.logger.info(f"Attack successful: {css_rule}")
                        results["successful_attacks"].append({
                            "modal_type": modal.modal_type.value,
                            "css_rule": css_rule,
                            "selector": modal.selector,
                            "execution_time": result.execution_time
                        })
                        
                        # Save successful attack to brand data
                        self._save_successful_attack(modal.modal_type.value, css_rule)
                        results["modals_bypassed"] += 1
                        break
                    else:
                        self.logger.info(f"Attack failed: {css_rule}")
            
            # Apply body/global fixes to clean up any remaining modal effects
            body_fixes = self._fix_body_scroll_lock(page)
            if body_fixes:
                self.logger.info(f"Applied additional fixes: {', '.join(body_fixes)}")
                results["body_fixes"] = body_fixes
            
            results["success"] = results["modals_bypassed"] == results["modals_detected"]
            results["total_time"] = time.time() - start_time
            
            self.logger.info(f"Modal bypass complete. {results['modals_bypassed']}/{results['modals_detected']} modals bypassed")
            return results
            
        except Exception as e:
            self.logger.error(f"Error during modal bypass: {str(e)}")
            results["total_time"] = time.time() - start_time
            return results

    def bypass_blocking_modals_only(self, page: Page, url: str) -> Dict[str, any]:
        """
        Optimized modal bypass that only targets modals actively blocking interactions.
        Much faster than full modal detection - only removes click-blocking elements.
        
        Args:
            page: Playwright page object
            url: Current page URL
            
        Returns:
            Dictionary with bypass results focused on blocking elements only
        """
        self.logger.info(f"Quick blocking modal check for {url}")
        
        results = {
            "url": url,
            "modals_detected": 0,
            "modals_bypassed": 0,
            "blocking_elements_found": [],
            "success": True
        }
        
        start_time = time.time()
        
        try:
            # Quick check for click-blocking elements
            blocking_modals = page.evaluate("""
                () => {
                    const blockingElements = [];
                    
                    // Strategy 1: Check for elements covering screen center (where buttons usually are)
                    const screenCenterX = window.innerWidth / 2;
                    const screenCenterY = window.innerHeight / 2;
                    
                    const centerElement = document.elementFromPoint(screenCenterX, screenCenterY);
                    
                    if (centerElement && centerElement !== document.body && centerElement !== document.documentElement) {
                        const style = window.getComputedStyle(centerElement);
                        const zIndex = parseInt(style.zIndex) || 0;
                        const rect = centerElement.getBoundingClientRect();
                        
                        // Check if it's likely a blocking modal (high z-index, large coverage)
                        const isLikelyBlocking = (
                            zIndex > 999 && 
                            (style.position === 'fixed' || style.position === 'absolute') &&
                            rect.width > window.innerWidth * 0.3 &&
                            rect.height > window.innerHeight * 0.3
                        );
                        
                        if (isLikelyBlocking) {
                            let selector = centerElement.tagName.toLowerCase();
                            if (centerElement.id) {
                                selector += '#' + centerElement.id;
                            } else if (centerElement.className) {
                                const classes = centerElement.className.split(' ').filter(c => c && c.length < 20).slice(0, 2).join('.');
                                if (classes) selector += '.' + classes;
                            }
                            
                            blockingElements.push({
                                selector: selector,
                                zIndex: zIndex,
                                type: 'center_blocking',
                                element: centerElement
                            });
                        }
                    }
                    
                    // Strategy 2: Check for visible common blocking modal selectors
                    const knownBlockingSelectors = [
                        '[role="dialog"]:not([style*="none"])',
                        '.modal:not([style*="none"])',
                        '.popup:not([style*="none"])',
                        '[data-modal]:not([style*="none"])',
                        '.overlay:not([style*="none"])',
                        '.modal-backdrop:not([style*="none"])',
                        '[id*="modal"]:not([style*="none"])',
                        '[id*="Modal"]:not([style*="none"])',
                        '[class*="modal"]:not([style*="none"])',
                        '[class*="Modal"]:not([style*="none"])'
                    ];
                    
                    knownBlockingSelectors.forEach(selector => {
                        try {
                            const elements = document.querySelectorAll(selector);
                            elements.forEach(el => {
                                const style = window.getComputedStyle(el);
                                const zIndex = parseInt(style.zIndex) || 0;
                                
                                if (style.display !== 'none' && 
                                    style.visibility !== 'hidden' && 
                                    zIndex > 0) {
                                    
                                    blockingElements.push({
                                        selector: selector,
                                        zIndex: zIndex,
                                        type: 'known_modal',
                                        element: el
                                    });
                                }
                            });
                        } catch (e) {
                            // Skip invalid selectors
                        }
                    });
                    
                    // Strategy 3: Check for body scroll lock (indicates modal is open)
                    const bodyStyle = window.getComputedStyle(document.body);
                    if (bodyStyle.overflow === 'hidden' || bodyStyle.position === 'fixed') {
                        blockingElements.push({
                            selector: 'body',
                            zIndex: 0,
                            type: 'scroll_lock',
                            element: document.body
                        });
                    }
                    
                    return blockingElements;
                }
            """)
            
            results["modals_detected"] = len(blocking_modals)
            
            if not blocking_modals:
                results["total_time"] = time.time() - start_time
                return results
            
            # Apply targeted removal only for blocking elements
            bypassed_count = 0
            for modal in blocking_modals:
                selector = modal["selector"]
                modal_type = modal["type"]
                
                try:
                    if modal_type == "scroll_lock":
                        # Fix body scroll lock
                        page.evaluate("""
                            () => {
                                document.body.style.overflow = 'auto';
                                document.body.style.position = 'static';
                                document.documentElement.style.overflow = 'auto';
                            }
                        """)
                        self.logger.info(f"Fixed body scroll lock")
                    else:
                        # Apply targeted hide CSS for blocking modals
                        css_rule = f"{selector} {{ display: none !important; pointer-events: none !important; z-index: -9999 !important; }}"
                        page.add_style_tag(content=css_rule)
                        self.logger.info(f"Hidden blocking element: {selector}")
                    
                    bypassed_count += 1
                    results["blocking_elements_found"].append({
                        "selector": selector,
                        "type": modal_type,
                        "bypassed": True
                    })
                    
                except Exception as e:
                    self.logger.warning(f"Failed to bypass {selector}: {str(e)}")
                    results["blocking_elements_found"].append({
                        "selector": selector,
                        "type": modal_type,
                        "bypassed": False,
                        "error": str(e)
                    })
            
            results["modals_bypassed"] = bypassed_count
            results["success"] = bypassed_count == len(blocking_modals)
            results["total_time"] = time.time() - start_time
            
            self.logger.info(f"Quick bypass complete: {bypassed_count}/{len(blocking_modals)} blocking elements removed in {results['total_time']:.2f}s")
            
            return results
            
        except Exception as e:
            self.logger.error(f"Error in blocking modal bypass: {str(e)}")
            results["total_time"] = time.time() - start_time
            results["error"] = str(e)
            results["success"] = False
            return results

    def _fix_body_scroll_lock(self, page: Page) -> List[str]:
        """Fix common modal-related body CSS locks"""
        fixes_applied = []
        
        try:
            # Check and fix body overflow
            body_fixes = page.evaluate("""
                () => {
                    const fixes = [];
                    const body = document.body;
                    const html = document.documentElement;
                    
                    // Fix body overflow
                    if (body.style.overflow === 'hidden' || 
                        getComputedStyle(body).overflow === 'hidden') {
                        body.style.overflow = 'auto !important';
                        fixes.push('body overflow reset');
                    }
                    
                    // Fix body position
                    if (body.style.position === 'fixed') {
                        body.style.position = 'static !important';
                        fixes.push('body position reset');
                    }
                    
                    // Fix html overflow  
                    if (html.style.overflow === 'hidden' ||
                        getComputedStyle(html).overflow === 'hidden') {
                        html.style.overflow = 'auto !important';
                        fixes.push('html overflow reset');
                    }
                    
                    // Remove common modal classes from body/html
                    const modalClasses = ['modal-open', 'no-scroll', 'locked', 'overlay-open'];
                    modalClasses.forEach(cls => {
                        if (body.classList.contains(cls)) {
                            body.classList.remove(cls);
                            fixes.push(`removed ${cls} from body`);
                        }
                        if (html.classList.contains(cls)) {
                            html.classList.remove(cls);
                            fixes.push(`removed ${cls} from html`);
                        }
                    });
                    
                    return fixes;
                }
            """)
            
            fixes_applied.extend(body_fixes)
            
            # Apply global CSS fixes for common modal issues
            global_css = """
                body, html {
                    overflow: auto !important;
                    position: static !important;
                    height: auto !important;
                    width: auto !important;
                }
                
                /* Common backdrop/overlay patterns */
                .modal-backdrop, .backdrop, .overlay-backdrop {
                    display: none !important;
                }
                
                /* Prevent scroll locks */
                .no-scroll, .modal-open, .locked {
                    overflow: auto !important;
                }
            """
            
            page.add_style_tag(content=global_css)
            fixes_applied.append("global CSS fixes applied")
            
        except Exception as e:
            fixes_applied.append(f"Error applying fixes: {str(e)}")
            
        return fixes_applied

    def _test_css_attack(self, page: Page, css_rule: str, selector: str) -> AttackResult:
        """
        Test a CSS attack to see if it successfully bypasses the modal.
        
        Args:
            page: Playwright page object
            css_rule: CSS rule to inject
            selector: Modal selector to target
            
        Returns:
            AttackResult with success/failure details
        """
        start_time = time.time()
        
        try:
            # Inject CSS attack
            full_css = f"{selector} {{ {css_rule} }}"
            page.add_style_tag(content=full_css)
            
            # Wait for CSS to take effect
            time.sleep(0.5)
            
            # Check if modal is still visible
            modal_still_visible = page.evaluate(f"""
                () => {{
                    const elements = document.querySelectorAll('{selector}');
                    for (const el of elements) {{
                        const style = window.getComputedStyle(el);
                        if (style.display !== 'none' && 
                            style.visibility !== 'hidden' && 
                            style.opacity !== '0') {{
                            return true;
                        }}
                    }}
                    return false;
                }}
            """)
            
            success = not modal_still_visible
            execution_time = time.time() - start_time
            
            return AttackResult(
                css_rule=css_rule,
                success=success,
                execution_time=execution_time
            )
            
        except Exception as e:
            execution_time = time.time() - start_time
            return AttackResult(
                css_rule=css_rule,
                success=False,
                execution_time=execution_time
            )

    def _get_known_attacks_for_modal(self, modal_type: str) -> List[str]:
        """Get known successful attacks for a modal type from brand data"""
        modal_bypasses = self.brand_data.get("modal_bypasses", {})
        return modal_bypasses.get(modal_type, [])

    def _save_successful_attack(self, modal_type: str, css_rule: str):
        """Save successful attack to brand data"""
        if "modal_bypasses" not in self.brand_data:
            self.brand_data["modal_bypasses"] = {}
        
        if modal_type not in self.brand_data["modal_bypasses"]:
            self.brand_data["modal_bypasses"][modal_type] = []
        
        # Only add if not already present
        if css_rule not in self.brand_data["modal_bypasses"][modal_type]:
            self.brand_data["modal_bypasses"][modal_type].append(css_rule)
            self.brand_data["modal_bypasses"]["last_updated"] = time.strftime("%Y-%m-%d")


# Convenience functions for easy integration
def bypass_page_modals(page: Page, url: str, brand_data: Dict = None) -> Dict[str, any]:
    """
    Convenience function to quickly bypass modals on a page.
    
    Args:
        page: Playwright page object
        url: Current page URL
        brand_data: Optional brand data dictionary for storing learned attacks
        
    Returns:
        Dictionary with bypass results
    """
    engine = ModalBypassEngine(brand_data)
    return engine.bypass_modals(page, url)


def bypass_blocking_modals_only(page: Page, url: str, brand_data: Dict = None) -> Dict[str, any]:
    """
    Convenience function to quickly bypass only blocking modals on a page.
    Optimized for speed - only removes elements that would block button clicks.
    
    Args:
        page: Playwright page object
        url: Current page URL
        brand_data: Optional brand data dictionary
        
    Returns:
        Dictionary with blocking modal bypass results
    """
    engine = ModalBypassEngine(brand_data)
    return engine.bypass_blocking_modals_only(page, url)