"""
Navigation Discovery Agent v3

Key improvement: Reduce LLM cognitive load by handling mechanical tasks in Python:
- Selector validation and conversion
- Visibility checks
- Fresh page verification
- API endpoint detection

LLM focuses on: Understanding the page structure and deciding what to interact with.
"""

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PRICING = {
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
}

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
config_env = Path(__file__).parent.parent.parent / "config" / ".env"
load_dotenv(config_env)

from anthropic import Anthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXTRACTIONS_DIR = Path(__file__).parent / "extractions"

# Standard viewport - must match what Playwright uses
VIEWPORT = {"width": 1280, "height": 800}

SYSTEM_PROMPT = """You are extracting navigation from a fashion website.

## YOUR GOAL
Extract all product category links from the site's navigation menu.

## AVAILABLE TOOLS
- take_snapshot: See the page content (accessibility tree)
- click/hover: Interact with elements using their UID from snapshot
- navigate_page: Go to URLs or reload
- list_network_requests: Check for API calls
- get_network_request: Get API response content
- evaluate_script: Run JavaScript in the page

## IMPORTANT TOOL: check_for_api
Call this AFTER opening/revealing the menu! Many sites fetch navigation data via API when the menu is triggered.
If it finds an API, use it! API extraction is always preferred over DOM scraping.

## IMPORTANT TOOL: validate_selector
When you identify an element to interact with, use validate_selector with:
- selector: A CSS selector you want to use

It returns visibility status and element details. Use this before finalizing pre_extraction_actions.

## IMPORTANT TOOL: test_extraction
Before calling save_and_finish, call test_extraction with your extraction_script.
It will reload the page, run pre_extraction_actions, execute your script, and report results.

## WORKFLOW
1. Navigate to URL
2. Take snapshot, find menu trigger (e.g., "Shop", "Menu", hamburger icon)
3. Click/hover to reveal the menu
4. **IMMEDIATELY call check_for_api** - the menu opening often triggers API calls!
5. If API found: use API method with api_parser
6. If no API: take snapshot of revealed menu, write extraction_script
7. Call validate_selector for any selectors in pre_extraction_actions
8. Call test_extraction to verify it works
9. Call save_and_finish

## KEY INSIGHT
Many modern fashion sites (Zara, H&M, etc.) load navigation via XHR/fetch when you open the menu.
ALWAYS check for API AFTER triggering the menu, not before!

## EXTRACTION SCRIPT RULES
- Must be a function that returns [{name, url, children}]
- NO interactions inside (hover/click go in pre_extraction_actions)
- Just read the visible DOM with querySelectorAll
- Filter duplicates, handle hierarchy if present

Example:
```javascript
function extractNavigation() {
  const results = [];
  document.querySelectorAll('nav a[href*="/collections"]').forEach(link => {
    results.push({
      name: link.textContent.trim(),
      url: link.href,
      children: []
    });
  });
  return results;
}
```
"""


class NavigationDiscoveryAgentV3:
    """Discovery agent with Python-side automation for mechanical tasks"""

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY required")

        self.client = Anthropic(api_key=self.api_key)
        self.model = model
        self.session: Optional[ClientSession] = None
        self.mcp_tools: List[Dict] = []
        self.brand_dir: Optional[Path] = None
        self.brand_url: Optional[str] = None

        # Store discovered data
        self.api_endpoint: Optional[str] = None
        self.pre_extraction_actions: List[Dict] = []
        self.extraction_script: Optional[str] = None

        # Full conversation log (no truncation)
        self.conversation_log: List[Dict] = []

        # Metrics
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    async def get_mcp_tools(self) -> List[Dict]:
        """Get tools from MCP server"""
        if not self.session:
            raise RuntimeError("Not connected")

        result = await self.session.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema
            }
            for tool in result.tools
        ]

    def get_tools(self) -> List[Dict]:
        """Get all available tools including our custom ones"""
        tools = self.mcp_tools.copy()

        # Custom tool: check_for_api
        tools.append({
            "name": "check_for_api",
            "description": "Automatically checks network requests for navigation/category API endpoints. Call this after page loads. Returns API endpoint details if found.",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        })

        # Custom tool: validate_selector
        tools.append({
            "name": "validate_selector",
            "description": "Validates a selector or converts a snapshot UID to a real CSS selector. Returns visibility status and the actual selector to use.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "uid": {
                        "type": "string",
                        "description": "The UID from snapshot (e.g., '1a2b3c')"
                    },
                    "selector": {
                        "type": "string",
                        "description": "A CSS selector to validate"
                    },
                    "description": {
                        "type": "string",
                        "description": "What this element is (e.g., 'Shop menu trigger')"
                    }
                }
            }
        })

        # Custom tool: test_extraction
        tools.append({
            "name": "test_extraction",
            "description": "Tests the full extraction flow: reloads page, runs pre_extraction_actions, executes extraction_script. Returns results or errors.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "extraction_script": {
                        "type": "string",
                        "description": "The JavaScript extraction function"
                    },
                    "pre_extraction_actions": {
                        "type": "array",
                        "description": "Actions to run before extraction [{action, selector}]",
                        "items": {"type": "object"}
                    }
                },
                "required": ["extraction_script"]
            }
        })

        # Custom tool: save_and_finish
        tools.append({
            "name": "save_and_finish",
            "description": "Save the extraction method and finish. Only call after test_extraction succeeds.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "enum": ["api", "embedded_json", "dom"],
                        "description": "Extraction method type"
                    },
                    "api_endpoint": {
                        "type": "string",
                        "description": "For API method: the endpoint URL"
                    },
                    "api_parser": {
                        "type": "string",
                        "description": "For API method: JS function to parse API response"
                    },
                    "extraction_script": {
                        "type": "string",
                        "description": "For DOM method: the extraction function"
                    },
                    "pre_extraction_actions": {
                        "type": "array",
                        "description": "For DOM method: actions before extraction",
                        "items": {"type": "object"}
                    },
                    "top_categories": {
                        "type": "array",
                        "description": "List of top-level category names",
                        "items": {"type": "string"}
                    },
                    "notes": {
                        "type": "string",
                        "description": "Brief notes about the method"
                    }
                },
                "required": ["method", "top_categories"]
            }
        })

        return tools

    async def call_mcp_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        """Call MCP tool and return result

        Returns full result string. Truncation for LLM is handled at a higher level.
        """
        if not self.session:
            raise RuntimeError("Not connected")

        result = await self.session.call_tool(name, arguments)

        if result.content:
            contents = []
            for block in result.content:
                if hasattr(block, 'text'):
                    contents.append(block.text)
                elif hasattr(block, 'data'):
                    contents.append(f"[Binary data: {block.mimeType}]")
            return "\n".join(contents) if contents else "No content"
        return "No content"

    async def check_for_api(self) -> str:
        """Check network requests for navigation API endpoints"""
        print("    [Python] Checking for API endpoints...")

        try:
            # Get XHR/fetch requests
            requests_result = await self.call_mcp_tool(
                "list_network_requests",
                {"resourceTypes": ["xhr", "fetch"]}
            )

            # Look for navigation-related endpoints
            nav_keywords = ["categor", "navigation", "menu", "nav", "header"]

            # Parse the requests result to find potential endpoints
            lines = requests_result.split("\n")
            candidates = []

            for line in lines:
                line_lower = line.lower()
                if any(kw in line_lower for kw in nav_keywords):
                    # Extract URL from the line
                    if "http" in line:
                        # Try to extract URL
                        match = re.search(r'(https?://[^\s"\']+)', line)
                        if match:
                            candidates.append(match.group(1))
                    # Also check for reqid to get full details
                    reqid_match = re.search(r'reqid[:\s]+(\d+)', line_lower)
                    if reqid_match:
                        candidates.append(f"reqid:{reqid_match.group(1)}")

            if candidates:
                # Check each candidate
                for candidate in candidates[:3]:  # Limit to first 3
                    if candidate.startswith("reqid:"):
                        reqid = candidate.split(":")[1]
                        try:
                            detail = await self.call_mcp_tool(
                                "get_network_request",
                                {"reqid": int(reqid)}
                            )
                            if '"categories"' in detail or '"navigation"' in detail or '"children"' in detail:
                                self.api_endpoint = candidate
                                return f"FOUND API ENDPOINT!\n\nRequest details:\n{detail[:2000]}\n\nThis appears to contain navigation data. Use this for extraction!"
                        except:
                            pass

                return f"Found potential API calls but none contained navigation data:\n{chr(10).join(candidates[:5])}\n\nProceeding with DOM extraction."

            return "No navigation API endpoints found. Proceed with DOM extraction."

        except Exception as e:
            return f"Error checking API: {e}. Proceed with DOM extraction."

    async def validate_selector(self, uid: Optional[str] = None, selector: Optional[str] = None, description: str = "") -> str:
        """Validate selector or convert UID to real CSS selector"""
        print(f"    [Python] Validating selector: uid={uid}, selector={selector}")

        js_code = """
        (uid, selector) => {
            let element = null;
            let foundSelector = null;

            // If UID provided, find element by data attribute (MCP adds these)
            if (uid) {
                // MCP snapshot UIDs correspond to elements - try to find by various methods
                // The snapshot doesn't directly map, so we need to be creative
                // For now, return an error suggesting to use evaluate_script to find the element
                return {
                    error: "UID lookup not directly supported. Use evaluate_script to find element by text/position.",
                    suggestion: "Provide a CSS selector or use evaluate_script to find the element"
                };
            }

            // If selector provided, validate it
            if (selector) {
                try {
                    element = document.querySelector(selector);
                    if (!element) {
                        return {
                            valid: false,
                            error: `Selector "${selector}" not found in DOM`
                        };
                    }

                    // Check visibility
                    const style = getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    const isVisible = style.display !== 'none' &&
                                     style.visibility !== 'hidden' &&
                                     rect.width > 0 && rect.height > 0;

                    // Get element details
                    return {
                        valid: true,
                        selector: selector,
                        isVisible: isVisible,
                        tagName: element.tagName.toLowerCase(),
                        text: element.textContent.trim().substring(0, 50),
                        ariaLabel: element.getAttribute('aria-label'),
                        classes: element.className,
                        rect: {
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height)
                        }
                    };
                } catch (e) {
                    return {
                        valid: false,
                        error: `Invalid selector "${selector}": ${e.message}`
                    };
                }
            }

            return { error: "Provide either uid or selector" };
        }
        """

        try:
            result = await self.call_mcp_tool(
                "evaluate_script",
                {"function": js_code, "args": [{"uid": uid or ""}, {"uid": selector or ""}]}
            )

            # Parse and format result
            return f"Selector validation result:\n{result}\n\nIf isVisible is false, this selector won't work in Playwright. Find a visible alternative."

        except Exception as e:
            return f"Error validating selector: {e}"

    async def test_extraction(self, extraction_script: str, pre_extraction_actions: List[Dict] = None) -> str:
        """Test full extraction flow on a fresh page"""
        print("    [Python] Testing extraction on fresh page...")

        pre_actions = pre_extraction_actions or []

        try:
            # Step 1: Reload page
            print("      Reloading page...")
            await self.call_mcp_tool("navigate_page", {"type": "reload"})
            await asyncio.sleep(3)  # Wait for page load

            # Step 2: Execute pre_extraction_actions
            for i, action in enumerate(pre_actions):
                action_type = action.get("action")
                selector = action.get("selector")

                if not action_type or not selector:
                    continue

                print(f"      Action {i+1}: {action_type} on {selector}")

                # First validate the selector exists and is visible
                validate_js = f"""
                () => {{
                    const el = document.querySelector('{selector}');
                    if (!el) return {{ found: false, error: 'Element not found' }};
                    const style = getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return {{
                        found: true,
                        visible: style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0,
                        rect: {{ x: rect.x, y: rect.y, width: rect.width, height: rect.height }}
                    }};
                }}
                """

                check_result = await self.call_mcp_tool("evaluate_script", {"function": validate_js})

                if "found: false" in check_result.lower() or '"found":false' in check_result.lower():
                    return f"FAILED: Pre-extraction action failed - selector '{selector}' not found after page reload.\n\nThis selector doesn't exist on fresh page load. You may need a different selector or additional actions."

                if "visible: false" in check_result.lower() or '"visible":false' in check_result.lower():
                    return f"WARNING: Selector '{selector}' exists but is not visible. It may be a mobile-only element. Check for a desktop-visible alternative."

                # Perform the action using MCP's click/hover
                if action_type == "hover":
                    # Use evaluate_script to hover since MCP hover needs UID
                    hover_js = f"""
                    () => {{
                        const el = document.querySelector('{selector}');
                        if (el) {{
                            const event = new MouseEvent('mouseenter', {{ bubbles: true }});
                            el.dispatchEvent(event);
                            return 'Hover dispatched';
                        }}
                        return 'Element not found';
                    }}
                    """
                    await self.call_mcp_tool("evaluate_script", {"function": hover_js})
                elif action_type == "click":
                    click_js = f"""
                    () => {{
                        const el = document.querySelector('{selector}');
                        if (el) {{
                            el.click();
                            return 'Click executed';
                        }}
                        return 'Element not found';
                    }}
                    """
                    await self.call_mcp_tool("evaluate_script", {"function": click_js})

                await asyncio.sleep(1)  # Wait for any animations

            # Step 3: Run extraction script
            print("      Running extraction script...")
            result = await self.call_mcp_tool(
                "evaluate_script",
                {"function": f"() => {{ {extraction_script}; return extractNavigation(); }}"}
            )

            # Parse and validate result
            try:
                # The result should be JSON array
                if "[]" in result or result.strip() == "[]":
                    return f"FAILED: Extraction returned empty array.\n\nResult: {result}\n\nThe script ran but found no categories. Check your selectors."

                # Try to count results
                if '"name"' in result:
                    count = result.count('"name"')
                    return f"SUCCESS: Extraction found approximately {count} categories.\n\nPreview:\n{result[:1500]}\n\nThis looks good! You can call save_and_finish."
                else:
                    return f"UNCERTAIN: Script returned but format unclear.\n\nResult: {result[:1000]}\n\nVerify this is the expected format."

            except Exception as e:
                return f"FAILED: Could not parse extraction result: {e}\n\nRaw result: {result[:500]}"

        except Exception as e:
            return f"FAILED: Test extraction error: {e}"

    def save_method(self, brand_name: str, brand_url: str, data: Dict) -> str:
        """Save the method_summary.json file"""
        method = data.get("method", "dom")

        method_summary = {
            "brand": brand_name,
            "url": brand_url,
            "method": method,
        }

        if method == "api":
            method_summary["api_endpoint"] = data.get("api_endpoint", "")
            method_summary["api_parser"] = data.get("api_parser", "")
        else:
            method_summary["pre_extraction_actions"] = data.get("pre_extraction_actions", [])
            method_summary["extraction_script"] = data.get("extraction_script", "")

        method_summary["top_level_categories"] = data.get("top_categories", [])
        method_summary["stats"] = {
            "total_categories": len(data.get("top_categories", [])),
            "max_depth": 2
        }
        method_summary["notes"] = data.get("notes", "")

        path = self.brand_dir / "method_summary.json"
        path.write_text(json.dumps(method_summary, indent=2))
        return f"Saved to {path}"

    async def handle_custom_tool(self, name: str, arguments: Dict) -> str:
        """Handle our custom tools"""
        if name == "check_for_api":
            return await self.check_for_api()
        elif name == "validate_selector":
            return await self.validate_selector(
                uid=arguments.get("uid"),
                selector=arguments.get("selector"),
                description=arguments.get("description", "")
            )
        elif name == "test_extraction":
            return await self.test_extraction(
                extraction_script=arguments.get("extraction_script", ""),
                pre_extraction_actions=arguments.get("pre_extraction_actions", [])
            )
        elif name == "save_and_finish":
            return "SAVE_AND_FINISH"  # Special marker
        else:
            return f"Unknown custom tool: {name}"

    async def discover_brand(self, brand_name: str, brand_url: str) -> Dict:
        """Run discovery for a single brand"""
        print(f"\n{'#'*60}")
        print(f"DISCOVERING: {brand_name}")
        print(f"URL: {brand_url}")
        print(f"{'#'*60}")

        start_time = time.time()
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.brand_url = brand_url
        self.conversation_log = []  # Reset conversation log

        self.brand_dir = EXTRACTIONS_DIR / brand_name
        self.brand_dir.mkdir(parents=True, exist_ok=True)

        # Set viewport to match Playwright
        print(f"Setting viewport to {VIEWPORT['width']}x{VIEWPORT['height']}...")
        try:
            await self.call_mcp_tool("resize_page", VIEWPORT)
        except Exception as e:
            print(f"Warning: Could not set viewport: {e}")

        tools = self.get_tools()

        # Initial message
        initial_message = {
            "role": "user",
            "content": f"""Discover navigation extraction for: {brand_url}

Start by:
1. Navigate to the URL
2. Call check_for_api to look for API endpoints
3. If no API found, take a snapshot and find the menu"""
        }
        messages = [initial_message]
        self.conversation_log.append({"turn": 0, "message": initial_message})

        max_turns = 25
        finished = False
        save_data = None

        for turn in range(max_turns):
            print(f"\n--- Turn {turn + 1}/{max_turns} ---")

            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=tools,
                messages=messages
            )

            # Track tokens
            if hasattr(response, 'usage'):
                self.total_input_tokens += response.usage.input_tokens
                self.total_output_tokens += response.usage.output_tokens

            # Process response - NO TRUNCATION for logging
            assistant_content = []
            tool_calls = []

            for block in response.content:
                if block.type == "text":
                    # Print truncated for console, but log full
                    print(f"Claude: {block.text[:300]}..." if len(block.text) > 300 else f"Claude: {block.text}")
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    tool_calls.append(block)
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input
                    })
                    print(f"Tool: {block.name}")

            assistant_message = {"role": "assistant", "content": assistant_content}
            messages.append(assistant_message)

            # Log full assistant message (no truncation)
            self.conversation_log.append({
                "turn": turn + 1,
                "message": assistant_message,
                "usage": {
                    "input_tokens": response.usage.input_tokens if hasattr(response, 'usage') else 0,
                    "output_tokens": response.usage.output_tokens if hasattr(response, 'usage') else 0
                }
            })

            # Process tool calls
            if tool_calls:
                tool_results_for_llm = []  # Truncated for LLM context
                tool_results_full = []     # Full for logging

                for tc in tool_calls:
                    # Check if it's our custom tool
                    if tc.name in ["check_for_api", "validate_selector", "test_extraction", "save_and_finish"]:
                        if tc.name == "save_and_finish":
                            save_data = tc.input
                            result = self.save_method(brand_name, brand_url, tc.input)
                            print(f">>> {result}")
                            tool_results_for_llm.append({
                                "type": "tool_result",
                                "tool_use_id": tc.id,
                                "content": result
                            })
                            tool_results_full.append({
                                "tool_name": tc.name,
                                "tool_input": tc.input,
                                "tool_use_id": tc.id,
                                "content": result
                            })
                            finished = True
                        else:
                            result = await self.handle_custom_tool(tc.name, tc.input)
                            # Truncate for LLM if needed
                            llm_result = result if len(result) <= 8000 else result[:8000] + "\n... (truncated)"
                            tool_results_for_llm.append({
                                "type": "tool_result",
                                "tool_use_id": tc.id,
                                "content": llm_result
                            })
                            tool_results_full.append({
                                "tool_name": tc.name,
                                "tool_input": tc.input,
                                "tool_use_id": tc.id,
                                "content": result  # Full result for log
                            })
                    else:
                        # MCP tool
                        try:
                            result = await self.call_mcp_tool(tc.name, tc.input)
                            # Truncate for LLM if needed
                            llm_result = result if len(result) <= 8000 else result[:8000] + "\n... (truncated)"
                            tool_results_for_llm.append({
                                "type": "tool_result",
                                "tool_use_id": tc.id,
                                "content": llm_result
                            })
                            tool_results_full.append({
                                "tool_name": tc.name,
                                "tool_input": tc.input,
                                "tool_use_id": tc.id,
                                "content": result  # Full result for log
                            })
                        except Exception as e:
                            print(f"Error: {e}")
                            tool_results_for_llm.append({
                                "type": "tool_result",
                                "tool_use_id": tc.id,
                                "content": f"Error: {e}",
                                "is_error": True
                            })
                            tool_results_full.append({
                                "tool_name": tc.name,
                                "tool_input": tc.input,
                                "tool_use_id": tc.id,
                                "content": f"Error: {e}",
                                "is_error": True
                            })

                # Send truncated results to LLM
                tool_results_message = {"role": "user", "content": tool_results_for_llm}
                messages.append(tool_results_message)

                # Log full tool results (NO truncation)
                self.conversation_log.append({
                    "turn": turn + 1,
                    "tool_results": tool_results_full
                })

                if finished:
                    break

            # Check for end without tools
            if response.stop_reason == "end_turn" and not tool_calls:
                print("Ended without saving - prompting to continue")
                prompt_message = {
                    "role": "user",
                    "content": "Please call test_extraction to verify your script works, then save_and_finish to complete."
                }
                messages.append(prompt_message)
                self.conversation_log.append({"turn": turn + 1, "system_prompt": prompt_message})

        # Calculate metrics
        duration = round(time.time() - start_time, 2)
        pricing = PRICING.get(self.model, {"input": 3.00, "output": 15.00})
        cost = round(
            (self.total_input_tokens / 1_000_000) * pricing["input"] +
            (self.total_output_tokens / 1_000_000) * pricing["output"],
            4
        )

        metrics = {
            "brand": brand_name,
            "url": brand_url,
            "model": self.model,
            "success": finished,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_turns": turn + 1,
            "duration_seconds": duration,
            "cost_usd": cost
        }

        (self.brand_dir / "discovery_metrics.json").write_text(json.dumps(metrics, indent=2))

        # Save full conversation log (NO TRUNCATION)
        conversation_log_data = {
            "brand": brand_name,
            "url": brand_url,
            "model": self.model,
            "system_prompt": SYSTEM_PROMPT,
            "discovered_at": datetime.now(timezone.utc).isoformat(),
            "conversation": self.conversation_log
        }
        (self.brand_dir / "discovery_conversation.json").write_text(
            json.dumps(conversation_log_data, indent=2, ensure_ascii=False)
        )

        print(f"\n{'='*40}")
        print(f"Finished: {'SUCCESS' if finished else 'FAILED'}")
        print(f"Turns: {turn + 1}")
        print(f"Tokens: {self.total_input_tokens:,} in / {self.total_output_tokens:,} out")
        print(f"Cost: ${cost:.4f}")
        print(f"Duration: {duration}s")

        return metrics

    async def run(self, brands: List[Dict]):
        """Run discovery for brands"""
        print("=" * 60)
        print("Navigation Discovery Agent v3")
        print("=" * 60)

        server_params = StdioServerParameters(
            command="npx",
            args=["chrome-devtools-mcp@latest", "--isolated"]
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                self.session = session
                self.mcp_tools = await self.get_mcp_tools()
                print(f"Connected. {len(self.mcp_tools)} MCP tools available.")

                results = {"success": [], "failed": []}

                for brand in brands:
                    try:
                        metrics = await self.discover_brand(brand["name"], brand["url"])
                        if metrics.get("success"):
                            results["success"].append(brand["name"])
                        else:
                            results["failed"].append(brand["name"])
                    except Exception as e:
                        print(f"Error: {e}")
                        import traceback
                        traceback.print_exc()
                        results["failed"].append(brand["name"])

                print("\n" + "=" * 60)
                print("SUMMARY")
                print("=" * 60)
                print(f"Success: {results['success']}")
                print(f"Failed: {results['failed']}")

                return results


async def main():
    args = sys.argv[1:]

    if not args:
        print("Usage: python discover_navigation_v3.py <brand_name> <url>")
        print("       python discover_navigation_v3.py zara https://www.zara.com/us/")
        return

    brand_name = args[0]
    brand_url = args[1] if len(args) > 1 else f"https://www.{brand_name}.com/"

    brands = [{"name": brand_name, "url": brand_url}]

    agent = NavigationDiscoveryAgentV3()
    await agent.run(brands)


if __name__ == "__main__":
    asyncio.run(main())
