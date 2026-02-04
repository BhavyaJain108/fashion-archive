"""
Embedded JSON extraction strategy.

Uses LLM to DISCOVER exact text patterns on first URL, then extracts WITHOUT LLM
on subsequent URLs using simple string matching.

Works with any format: Next.js streaming, escaped JSON, React state, etc.
"""

import json
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

import sys
sys.path.insert(0, str(__file__).rsplit('/', 2)[0])
sys.path.insert(0, str(__file__).rsplit('/', 4)[0])  # For llm_handler

from models import Product, Variant, ExtractionResult, ExtractionStrategy
from strategies.base import BaseStrategy, PageData

try:
    from backend.scraper.llm_handler import LLMHandler
except ImportError:
    try:
        from scraper.llm_handler import LLMHandler
    except ImportError:
        LLMHandler = None


# Pydantic model for extraction patterns (what LLM returns during discovery)
class ExtractionPatterns(BaseModel):
    """Regex patterns to extract product data. Each pattern should have a capture group for the value."""
    title_pattern: str = Field(description="Regex to capture product title, e.g., '\\\\\"productSet\\\\\":\\{\\\\\"title\\\\\":\\\\\"([^\\\\\"]+)\\\\\"'")
    price_pattern: str = Field(description="Regex to capture price, e.g., '\\\\\"maxVariantPrice\\\\\":([0-9.]+)'")
    description_pattern: Optional[str] = Field(default=None, description="Regex to capture description")
    category_pattern: Optional[str] = Field(default=None, description="Regex to capture category")
    variant_size_pattern: Optional[str] = Field(default=None, description="Regex to capture variant sizes (use findall)")
    variant_stock_pattern: Optional[str] = Field(default=None, description="Regex to capture variant stock counts")




class ExtractedProduct(BaseModel):
    """Structured product data from LLM extraction."""
    title: str = Field(description="Product name/title")
    price: Optional[float] = Field(default=None, description="Product price as number")
    currency: str = Field(default="USD", description="Currency code")
    description: Optional[str] = Field(default="", description="Product description")
    brand: Optional[str] = Field(default=None, description="Brand name")
    category: Optional[str] = Field(default=None, description="Product category")
    sku: Optional[str] = Field(default=None, description="Product SKU")
    images: list[str] = Field(default=[], description="Image URLs")
    variants: list[dict] = Field(default=[], description="Product variants with size/color/price/available/stock_count")


IDENTIFY_DATA_PROMPT = """Extract product information from this page data.

For each field, return:
1. The VALUE you found
2. The PATTERN - the key structure with placeholders:
   - {{{{SLUG}}}} = where the product slug appears (we replace with actual slug from URL)
   - {{{{VALUE}}}} = where a single value appears
   - {{{{ARRAY}}}} = where an array of values appears (like sizes: ["S","M","L"])
3. Your REASONING for why this pattern is unique

RULES:
- ONLY return patterns that EXACTLY exist in the data - do not guess or assume
- Include enough keys/structure to make the pattern unique
- Do NOT include any actual product values - only keys and placeholders
- A pattern like "title":"{{{{VALUE}}}}" is TOO GENERIC - add more context
- If a field is not found, write "NOT_FOUND" for the value
- Look at what keys ACTUALLY surround each value in the data

Format:
PRODUCT_NAME: <the actual product name>
PRODUCT_NAME_PATTERN: <pattern with {{{{VALUE}}}} - use {{{{SLUG}}}} only if it appears next to title in the data>
PRODUCT_NAME_REASONING: <why unique>

PRICE: <price as number>
PRICE_PATTERN: <pattern with {{{{VALUE}}}}>
PRICE_REASONING: <why unique>

DESCRIPTION: <product description text, or NOT_FOUND>
DESCRIPTION_PATTERN: <pattern with {{{{VALUE}}}}, or NOT_FOUND>
DESCRIPTION_REASONING: <why unique>

CATEGORY: <product category, or NOT_FOUND>
CATEGORY_PATTERN: <pattern with {{{{VALUE}}}}, or NOT_FOUND>
CATEGORY_REASONING: <why unique>

VARIANTS: <comma-separated sizes like XXS,XS,S,M,L,XL, or NOT_FOUND>
VARIANTS_PATTERN: <pattern with {{{{ARRAY}}}} to capture the sizes array, or NOT_FOUND>
VARIANTS_REASONING: <why unique>

IMAGE: <one product image URL, or NOT_FOUND>
IMAGE_PATTERN: <pattern with {{{{VALUE}}}}, or NOT_FOUND>
IMAGE_REASONING: <why unique>

Example:
PRODUCT_NAME: Classic T-Shirt
PRODUCT_NAME_PATTERN: "tags":{{{{ARRAY}}}},"title":"{{{{VALUE}}}}"
PRODUCT_NAME_REASONING: tags array before title is unique to product object

PRICE: 45
PRICE_PATTERN: "maxVariantPrice":{{{{VALUE}}}}
PRICE_REASONING: maxVariantPrice key is unique to product pricing

Data:
{script_content}
"""

EXTRACT_PROMPT = """Extract the product information from this page data.

Return ONLY a JSON object. No explanation, no markdown, no text before or after.

{
  "title": "exact product name",
  "price": 0,
  "currency": "USD",
  "description": "full product description",
  "brand": "brand name or null",
  "sku": "product SKU or null",
  "category": "product category or null",
  "variants": [
    {"size": "M", "color": "Black", "price": 0, "available": true}
  ],
  "images": ["url1", "url2"]
}

IMPORTANT: If a field is not found, use null (not strings like "unknown" or "N/A").
Price must be a number or null. Return actual image URLs, not placeholders.

Page content:
"""


class EmbeddedJsonStrategy(BaseStrategy):
    """
    Extract product data from embedded JSON/scripts.

    Two modes:
    1. Discovery (first URL): LLM identifies exact text patterns, saves them
    2. Extraction (subsequent URLs): Use string matching with patterns, NO LLM
    """

    strategy_type = ExtractionStrategy.DOM_FALLBACK

    def __init__(self, patterns_dir: Optional[Path] = None, debug: bool = True):
        self.llm = LLMHandler() if LLMHandler else None
        self.patterns_dir = patterns_dir or Path(__file__).parent.parent / "extraction_patterns"
        self.patterns_dir.mkdir(exist_ok=True)
        self.debug = debug
        self.debug_dir = self.patterns_dir / "debug"
        if self.debug:
            self.debug_dir.mkdir(exist_ok=True)

    async def extract(self, url: str, page_data: Optional[PageData] = None) -> ExtractionResult:
        """Extract product using saved patterns only. NO LLM calls.

        Pattern discovery happens during the discovery phase via _discover_patterns().
        Ground truth extraction happens via extract_ground_truth().
        This method only applies saved patterns - pure string matching.

        Args:
            url: Product page URL
            page_data: Page data with HTML

        Returns:
            ExtractionResult with whatever fields the patterns could extract.
            May be partial - that's OK, other strategies cover other fields.
        """
        try:
            if not page_data or not page_data.html:
                return ExtractionResult.failure(self.strategy_type, "No HTML provided")

            domain = self._get_domain(url)
            saved_patterns = self._load_patterns(domain)

            if not saved_patterns:
                return ExtractionResult.failure(self.strategy_type, f"No patterns saved for {domain}")

            # Use saved patterns with string matching - NO LLM!
            filtered_content, slug, _ = self._filter_scripts_by_slug(page_data.html, url)
            product_data = self._extract_with_patterns(filtered_content, saved_patterns, slug)

            if not product_data:
                return ExtractionResult.failure(self.strategy_type, "Pattern extraction returned no data")

            extracted_fields = list(product_data.keys())
            print(f"    [dom_fallback] Pattern extraction: got {extracted_fields}")

            # Return whatever we got - may be partial, that's OK
            product = self._parse_product(product_data, url, page_data)
            return ExtractionResult.from_product(product, self.strategy_type)

        except Exception as e:
            return ExtractionResult.failure(self.strategy_type, f"Error: {e}")

    def can_handle(self, url: str, page_data: Optional[PageData] = None) -> bool:
        """Check if page has embedded product-like scripts."""
        if not page_data or not page_data.html:
            return False

        # Check if we have saved patterns (can work without LLM)
        domain = self._get_domain(url)
        if self._load_patterns(domain):
            return True

        # Otherwise need LLM
        if not self.llm:
            return False

        # Look for scripts with product indicators
        html = page_data.html.lower()
        has_product_data = 'price' in html and (
            'variants' in html or
            'variant' in html or
            'size' in html or
            'sizes' in html or
            'productdetail' in html or
            '__next_data__' in html or
            '__next_f' in html
        )
        return has_product_data

    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.netloc.replace('www.', '')

    def _extract_slug_from_url(self, url: str) -> Optional[str]:
        """Extract product slug from URL path."""
        from urllib.parse import urlparse, unquote
        parsed = urlparse(url)
        path = unquote(parsed.path)

        # Get the last meaningful segment of the path
        segments = [s for s in path.split('/') if s and s not in ('product', 'products', 'p', 'item', 'items', 'us', 'en', 'uk', 'eu')]
        if not segments:
            return None

        # Try last segment first, if too short try second-to-last
        slug = segments[-1]
        if len(slug) <= 2 and len(segments) > 1:
            slug = segments[-2]

        # Remove common extensions and query-like suffixes
        slug = re.sub(r'\.(html?|aspx?|php|jsp)$', '', slug, flags=re.IGNORECASE)

        # Remove size/color parameters sometimes appended
        slug = re.sub(r'\?.*$', '', slug)

        return slug if len(slug) > 2 else None

    def _build_fuzzy_pattern(self, slug: str) -> re.Pattern:
        """Build a fuzzy regex pattern from slug to match variations."""
        # Split by common separators
        words = re.split(r'[-_\s]+', slug)

        # Join with pattern that matches dash, underscore, space, or nothing
        fuzzy_pattern = r'[-_\s]?'.join(re.escape(word) for word in words)

        return re.compile(fuzzy_pattern, re.IGNORECASE)

    def _filter_scripts_by_slug(self, html: str, url: str) -> tuple[str, str, list[str]]:
        """
        Filter HTML to only script contents containing the product slug.

        Returns:
            tuple: (filtered_content, slug, list_of_matching_scripts)
        """
        slug = self._extract_slug_from_url(url)
        if not slug:
            # Fallback: return truncated HTML if we can't extract slug
            return html[:50000], "", []

        fuzzy_pattern = self._build_fuzzy_pattern(slug)

        # Extract all script tag contents
        scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)

        # Filter to scripts containing the slug (fuzzy match)
        matching_scripts = [s for s in scripts if fuzzy_pattern.search(s)]

        if not matching_scripts:
            # No matches - fallback to truncated HTML
            return html[:50000], slug, []

        # Join matching scripts with separator for context
        filtered_content = "\n\n--- SCRIPT BOUNDARY ---\n\n".join(matching_scripts)

        return filtered_content, slug, matching_scripts

    def _discover_patterns(self, html: str, url: str, feedback: Optional[str] = None, domain: str = "unknown") -> Optional[Dict[str, Any]]:
        """Use LLM to identify data values, then build patterns programmatically."""
        # Filter to only scripts containing the product slug
        filtered_content, slug, matching_scripts = self._filter_scripts_by_slug(html, url)

        print(f"    [dom_fallback] Slug: {slug}")
        print(f"    [dom_fallback] Filtered {len(matching_scripts)} scripts, {len(filtered_content):,} chars (from {len(html):,})")

        # Normalize: convert backslash-quotes to regular quotes
        normalized = self._normalize_html(filtered_content)

        # Step 1: Ask LLM to identify the product data values
        prompt = IDENTIFY_DATA_PROMPT.format(script_content=normalized)
        result = self.llm.call(prompt=prompt, expected_format="text", max_tokens=1500, operation="dom_pattern_discovery")

        if not result.get("success"):
            self._save_debug(domain, slug, normalized, "LLM CALL FAILED", {}, matching_scripts)
            return None

        response = result.get("response", "")
        print(f"    [dom_fallback] LLM identified: {response[:100]}...")

        # Step 2: Parse LLM response
        patterns = {}
        llm_identified = {}

        # Define all fields we're looking for
        fields = [
            ("PRODUCT_NAME", "title_pattern", "title"),
            ("PRICE", "price_pattern", "price"),
            ("DESCRIPTION", "description_pattern", "description"),
            ("CATEGORY", "category_pattern", "category"),
            ("VARIANTS", "variants_pattern", "variants"),
            ("IMAGE", "image_pattern", "image"),
        ]

        for line in response.strip().split("\n"):
            line = line.strip()
            if not line:
                continue

            for field_name, pattern_key, field_type in fields:
                if line.startswith(f"{field_name}:") and "_PATTERN" not in line and "_REASON" not in line:
                    value = line.split(":", 1)[1].strip()
                    if value.upper() != "NOT_FOUND":
                        llm_identified[field_name] = value
                elif line.startswith(f"{field_name}_PATTERN:"):
                    value = line.split(":", 1)[1].strip()
                    if value.upper() != "NOT_FOUND":
                        llm_identified[f"{field_name}_PATTERN"] = value
                elif line.startswith(f"{field_name}_REASONING:"):
                    llm_identified[f"{field_name}_REASONING"] = line.split(":", 1)[1].strip()
                    # Convert pattern to regex and validate extracted value matches GT
                    if f"{field_name}_PATTERN" in llm_identified:
                        pattern = self._pattern_to_regex(llm_identified[f"{field_name}_PATTERN"], field_type)
                        if pattern:
                            # Apply pattern to HTML and compare extracted value to GT
                            test_pattern = pattern.replace('{{SLUG}}', re.escape(slug)) if slug else pattern
                            match = re.search(test_pattern, normalized)
                            if match:
                                extracted_value = match.group(1) if match.groups() else None
                                gt_value = llm_identified.get(field_name)
                                if extracted_value and gt_value and extracted_value.strip() == gt_value.strip():
                                    patterns[pattern_key] = pattern
                                    print(f"    [dom_fallback] Pattern for {field_name} verified: '{extracted_value}' matches GT")
                                else:
                                    print(f"    [dom_fallback] Pattern for {field_name} value mismatch: extracted '{extracted_value}' vs GT '{gt_value}'")
                            else:
                                print(f"    [dom_fallback] Pattern for {field_name} doesn't match HTML, skipping")

        # Save debug file
        print(f"    [dom_fallback] About to save debug, patterns={list(patterns.keys())}")
        try:
            self._save_debug(domain, slug, normalized, response, patterns, matching_scripts, llm_identified)
            print(f"    [dom_fallback] Debug saved successfully")
        except Exception as e:
            print(f"    [dom_fallback] Debug save failed: {e}")
            import traceback
            traceback.print_exc()

        return patterns if patterns else None

    def _pattern_to_regex(self, pattern: str, field_type: str) -> Optional[str]:
        r"""Convert LLM pattern with {{SLUG}}, {{VALUE}}, and {{ARRAY}} placeholders to regex.

        - {{SLUG}} stays as {{SLUG}} (replaced with actual slug at extraction time)
        - {{VALUE}} becomes capture group: ([^"]+) for strings, ([0-9.]+) for numbers
        - {{ARRAY}} becomes capture group for array contents: ([^\]]+)
        """
        if not pattern:
            return None

        # Use placeholders to protect during escaping
        slug_placeholder = "___SLUG_PLACEHOLDER___"
        value_placeholder = "___VALUE_PLACEHOLDER___"
        array_placeholder = "___ARRAY_PLACEHOLDER___"

        # Replace our placeholders with internal ones
        working = pattern.replace("{{SLUG}}", slug_placeholder)
        working = working.replace("{{VALUE}}", value_placeholder)
        working = working.replace("{{ARRAY}}", array_placeholder)

        # Escape for regex
        escaped = re.escape(working)

        # Replace internal placeholders with final values
        escaped = escaped.replace(re.escape(slug_placeholder), "{{SLUG}}")

        # Choose capture group based on field type
        if field_type == "price":
            capture = r'([0-9.]+)'
        elif field_type == "image":
            capture = r'([^"]+)'  # URL
        else:
            capture = r'([^"]+)'  # Default for strings
        escaped = escaped.replace(re.escape(value_placeholder), capture)

        # Array capture - gets the entire array including brackets
        # Use non-greedy match for nested array content
        escaped = escaped.replace(re.escape(array_placeholder), r'(\[[^\]]*\])')

        return escaped

    def _line_to_pattern(self, line: str, value: str, field_type: str, variables: List[str] = None) -> Optional[str]:
        """Convert a line + value into a regex pattern.

        - value is replaced with a capture group
        - variables are replaced with wildcards (no capture)
        """
        if not line or not value:
            return None

        variables = variables or []
        value = value.strip()

        # First, replace variables with placeholders
        # Use unique placeholders that won't appear in real data
        var_placeholder = "___VAR_PLACEHOLDER___"
        working_line = line
        for i, var in enumerate(variables):
            var = var.strip()
            if var and var in working_line:
                working_line = working_line.replace(var, f"{var_placeholder}{i}", 1)

        # Find value in the working line
        idx = working_line.find(value)
        if idx == -1:
            # Try the value as it might appear (e.g., price without decimals)
            if field_type == "price":
                try:
                    int_val = str(int(float(value)))
                    idx = working_line.find(int_val)
                    if idx != -1:
                        value = int_val
                except:
                    pass
            if idx == -1:
                return None

        # Replace value with placeholder
        value_placeholder = "___VALUE_PLACEHOLDER___"
        working_line = working_line[:idx] + value_placeholder + working_line[idx + len(value):]

        # Escape the entire line for regex
        escaped = re.escape(working_line)

        # Replace value placeholder with capture group
        if field_type == "price":
            capture = r'([0-9.]+)'
        else:
            capture = r'([^"]+)'
        escaped = escaped.replace(re.escape(value_placeholder), capture)

        # Replace variable placeholders with {{SLUG}} placeholder (to be replaced at extraction time)
        # This lets us use the actual slug from URL for precise matching
        for i in range(len(variables)):
            escaped = escaped.replace(re.escape(f"{var_placeholder}{i}"), r'{{SLUG}}')

        return escaped

    def _build_pattern_for_value(self, html: str, value: str, field_type: str) -> Optional[str]:
        """Build a regex pattern by finding where a value appears in HTML. DEPRECATED - use _line_to_pattern."""
        value = value.strip()
        if not value or value.upper() in ("NONE", "N/A", "NOT FOUND"):
            return None

        # Find the value in HTML
        idx = html.find(value)
        if idx == -1:
            # Try case-insensitive search
            lower_html = html.lower()
            lower_value = value.lower()
            idx = lower_html.find(lower_value)
            if idx == -1:
                return None
            # Get the actual case from HTML
            value = html[idx:idx + len(value)]

        # Get context before the value (enough to find the key)
        before = html[max(0, idx - 50):idx]
        after = html[idx + len(value):idx + len(value) + 20]

        if field_type in ("PRICE", "PRICE_LINE"):
            # For prices, look for patterns like "price":320 or "maxVariantPrice":320
            match = re.search(r'"(\w*[Pp]rice\w*)":\s*"?$', before)
            if match:
                key = match.group(1)
                return f'"{key}":\\s*"?([0-9.]+)'
            # Also try generic number pattern
            match = re.search(r'"(\w+)":\s*"?$', before)
            if match:
                key = match.group(1)
                return f'"{key}":\\s*"?([0-9.]+)'
        else:
            # For strings like product name, look for "key":"value" pattern
            match = re.search(r'"(\w+)":\s*"$', before)
            if match:
                key = match.group(1)
                return f'"{key}":\\s*"([^"]+)"'

        return None

    def _merge_patterns(self, old_patterns: Dict[str, Any], new_patterns: Dict[str, Any]) -> Dict[str, Any]:
        """Merge old and new patterns, preferring new patterns."""
        merged = dict(old_patterns)
        merged.update(new_patterns)
        return merged

    def _normalize_html(self, html: str) -> str:
        """Normalize HTML by converting backslash-quotes to regular quotes."""
        return html.replace('\\"', '"')

    def _extract_with_patterns(self, html: str, patterns: Dict[str, Any], slug: str = None) -> Optional[Dict]:
        """Extract product data using regex patterns - NO LLM."""
        product_data = {}

        # Normalize HTML for consistent pattern matching
        normalized = self._normalize_html(html)

        # Replace {{SLUG}} placeholder with actual slug if provided
        def prepare_pattern(pattern: str) -> str:
            if slug and '{{SLUG}}' in pattern:
                return pattern.replace('{{SLUG}}', re.escape(slug))
            return pattern

        # Extract title (use last capture group - the VALUE)
        if patterns.get('title_pattern'):
            pattern = prepare_pattern(patterns['title_pattern'])
            match = re.search(pattern, normalized)
            if match:
                product_data['title'] = self._clean_value(match.group(match.lastindex or 1))

        # Extract price (use last capture group)
        if patterns.get('price_pattern'):
            pattern = prepare_pattern(patterns['price_pattern'])
            match = re.search(pattern, normalized)
            if match:
                try:
                    product_data['price'] = float(match.group(match.lastindex or 1))
                except ValueError:
                    pass

        # Extract description (use last capture group)
        if patterns.get('description_pattern'):
            pattern = prepare_pattern(patterns['description_pattern'])
            match = re.search(pattern, normalized)
            if match:
                product_data['description'] = self._clean_value(match.group(match.lastindex or 1))

        # Extract category (use last capture group)
        if patterns.get('category_pattern'):
            pattern = prepare_pattern(patterns['category_pattern'])
            match = re.search(pattern, normalized)
            if match:
                product_data['category'] = self._clean_value(match.group(match.lastindex or 1))

        # Extract variants (capture array and parse)
        if patterns.get('variants_pattern'):
            pattern = prepare_pattern(patterns['variants_pattern'])
            match = re.search(pattern, normalized)
            if match:
                # Use the last capture group (the array) - pattern may have multiple groups
                array_content = match.group(match.lastindex or 1)
                # Parse array content: "XXS","XS","S","M","L" -> ['XXS', 'XS', 'S', 'M', 'L']
                sizes = re.findall(r'"([^"]+)"', array_content)
                variants = [{'size': size} for size in sizes]
                product_data['variants'] = variants

        # Extract image
        if patterns.get('image_pattern'):
            pattern = prepare_pattern(patterns['image_pattern'])
            matches = re.findall(pattern, normalized)
            if matches:
                images = []
                for img in matches:
                    if isinstance(img, tuple):
                        img = img[0]
                    if img and img.startswith('http'):
                        images.append(img)
                if images:
                    product_data['images'] = images[:20]  # Limit to 20

        # Always try to find images
        images = self._find_images(html)
        if images:
            product_data['images'] = images

        return product_data if product_data else None

    def _extract_between(self, text: str, prefix: Optional[str], suffix: Optional[str]) -> Optional[str]:
        """Extract text between prefix and suffix."""
        if not prefix or not suffix:
            return None

        # Normalize escape sequences for matching
        # The prefix/suffix from LLM might have literal backslashes
        search_prefix = (prefix or '').replace('\\\\', '\\')
        search_suffix = (suffix or '').replace('\\\\', '\\')

        # Try to find the pattern
        start_idx = text.find(search_prefix)
        if start_idx == -1:
            # Try with original (maybe already escaped correctly)
            start_idx = text.find(prefix)
            if start_idx == -1:
                return None
            search_prefix = prefix

        start_idx += len(search_prefix)

        # Find the suffix after the prefix
        end_idx = text.find(search_suffix if search_suffix != suffix else suffix, start_idx)
        if end_idx == -1:
            end_idx = text.find(suffix, start_idx)
        if end_idx == -1:
            return None

        value = text[start_idx:end_idx]

        # Don't return if value is too long (probably matched wrong)
        if len(value) > 5000:
            return None

        return value

    def _extract_variants(self, html: str, patterns: Dict[str, Any]) -> List[Dict]:
        """Extract all variants using the size pattern."""
        variants = []

        size_prefix = (patterns.get('variant_size_prefix') or '').replace('\\\\', '\\')
        size_suffix = (patterns.get('variant_size_suffix') or '').replace('\\\\', '\\')
        stock_prefix = (patterns.get('variant_stock_prefix') or '').replace('\\\\', '\\')
        stock_suffix = (patterns.get('variant_stock_suffix') or '').replace('\\\\', '\\')

        if not size_prefix or not size_suffix:
            return variants

        # Find all size values
        pos = 0
        seen_sizes = set()
        while True:
            start = html.find(size_prefix, pos)
            if start == -1:
                break
            start += len(size_prefix)
            end = html.find(size_suffix, start)
            if end == -1:
                break

            size = html[start:end]
            pos = end + 1

            # Filter to valid sizes
            if len(size) > 20 or size in seen_sizes:
                continue
            if not self._is_valid_size(size):
                continue

            seen_sizes.add(size)
            variant = {'size': self._clean_value(size)}

            # Try to find stock near this size (within 200 chars)
            if stock_prefix and stock_suffix:
                context_start = max(0, start - 100)
                context_end = min(len(html), end + 200)
                context = html[context_start:context_end]

                stock_start = context.find(stock_prefix)
                if stock_start != -1:
                    stock_start += len(stock_prefix)
                    stock_end = context.find(stock_suffix, stock_start)
                    if stock_end != -1:
                        stock_str = context[stock_start:stock_end]
                        try:
                            stock = int(re.sub(r'[^\d]', '', stock_str))
                            variant['stock_count'] = stock
                            variant['available'] = stock > 0
                        except ValueError:
                            pass

            variants.append(variant)

            if len(variants) >= 20:
                break

        return variants

    def _is_valid_size(self, size: str) -> bool:
        """Check if a string looks like a valid size."""
        size = size.strip().upper()
        common = {'XXS', 'XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL', 'OS', 'ONE SIZE', 'FREE', 'UNIQUE'}
        if size in common:
            return True
        # Numeric sizes: 6, 7.5, 32, etc.
        if re.match(r'^[0-9]{1,2}(\.[05])?$', size):
            return True
        # Letter sizes: S, M, XL, XXS, etc.
        if re.match(r'^[XSML]{1,4}$', size):
            return True
        # Range sizes: XS-S, M-L, XL-XXL, 32-34, etc.
        if re.match(r'^[A-Z0-9]{1,4}[-/][A-Z0-9]{1,4}$', size):
            return True
        if len(size) <= 5:
            return True
        return False

    def _clean_value(self, value: str) -> str:
        """Clean extracted value."""
        if not value:
            return value
        # Unescape common sequences
        value = value.replace('\\n', '\n')
        value = value.replace('\\r', '')
        value = value.replace('\\t', ' ')
        value = value.replace('\\"', '"')
        value = value.replace("\\'", "'")
        value = value.replace('\\/', '/')
        # Remove leading/trailing whitespace
        value = value.strip()
        return value

    def _find_images(self, html: str) -> List[str]:
        """Find image URLs in HTML."""
        images = []

        # Match any https image URL
        pattern = r'https://[^\s"\'<>]+\.(?:jpg|jpeg|png|webp)(?:\?[^\s"\'<>]*)?'
        matches = re.findall(pattern, html, re.IGNORECASE)
        for url in matches:
            url = url.rstrip('",\\')
            if url not in images:
                images.append(url)

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for img in images:
            base = img.split('?')[0]
            if base not in seen:
                seen.add(base)
                unique.append(img)

        return unique[:50]

    def _build_extraction_content(self, page_data: PageData) -> str:
        """Build best-signal content from multiple page data sources for LLM extraction."""
        html = page_data.html or ""
        parts = []

        # 1. Visible text — what the user actually sees on the page (ctrl+a ctrl+v)
        if page_data.visible_text and len(page_data.visible_text.strip()) > 50:
            parts.append("=== Visible Page Text ===")
            parts.append(page_data.visible_text.strip()[:5000])

        # 2. LD+JSON blocks (structured, works for non-Shopify)
        ld_json_blocks = re.findall(
            r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        )
        if ld_json_blocks:
            parts.append("=== LD+JSON ===")
            for block in ld_json_blocks:
                parts.append(block.strip()[:5000])

        # 3. Microdata (itemprop) tags
        microdata = re.findall(
            r'<meta[^>]*itemprop=["\']([^"\']+)["\'][^>]*content=["\']([^"\']*)["\'][^>]*/?>',
            html, re.IGNORECASE
        )
        if microdata:
            parts.append("=== Microdata ===")
            parts.append("\n".join(f"{k}: {v}" for k, v in microdata[:20]))

        # 4. Shopify-style filtered scripts (only if actual matches found)
        try:
            if page_data.url:
                filtered, slug, matches = self._filter_scripts_by_slug(html, page_data.url)
                if matches:
                    parts.append("=== Product Scripts ===")
                    parts.append(filtered[:20000])
        except Exception:
            pass

        # 5. API intercept data (if still little content)
        if len("\n".join(parts)) < 500 and page_data.json_responses:
            parts.append("=== API Responses ===")
            for url, data in list(page_data.json_responses.items())[:3]:
                snippet = json.dumps(data)[:5000] if not isinstance(data, str) else data[:5000]
                parts.append(f"URL: {url}\n{snippet}")

        # 6. Fall back to raw HTML only if nothing else worked
        if not parts:
            return html[:30000]

        content = "\n\n".join(parts)
        if len(content) > 30000:
            content = content[:30000] + "\n...[truncated]"
        return content

    def extract_ground_truth(self, page_data: PageData) -> Optional[dict]:
        """
        Single LLM call to extract full product data from page.

        Serves as both:
        - Ground truth for validating which cheaper strategy is correct per field
        - Dom fallback extraction result

        Returns raw dict with product fields, or None if LLM fails.
        """
        if not self.llm:
            return None

        content = self._build_extraction_content(page_data)

        # Use response_model for structured output (guarantees valid JSON)
        result = self.llm.call(
            prompt=EXTRACT_PROMPT + content,
            expected_format="json",
            response_model=ExtractedProduct,
            max_tokens=2000,
            operation="ground_truth_extraction",
        )

        if not result.get("success"):
            print(f"    [ground_truth] LLM call failed: {result.get('error', 'unknown')}")
            return None

        data = result.get("data") or result.get("response")
        if not data:
            return None

        if hasattr(data, "model_dump"):
            data = data.model_dump()
        elif isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, ValueError):
                print(f"    [ground_truth] Failed to parse JSON: {data[:200]}")
                return None

        if isinstance(data, dict):
            # Normalize price
            price = data.get("price")
            if isinstance(price, str):
                try:
                    price = float(price)
                except (ValueError, TypeError):
                    price = None
            elif not isinstance(price, (int, float)):
                price = None
            data["price"] = price
            return data
        return None

    def _parse_product(self, data: dict, url: str, page_data: Optional[PageData] = None) -> Product:
        """Parse extracted data into Product model."""
        variants = []
        for v in data.get('variants', []):
            variant = Variant(
                size=v.get('size'),
                color=v.get('color'),
                sku=v.get('sku'),
                price=v.get('price'),
                available=v.get('available'),
                stock_count=v.get('stock_count'),
            )
            variants.append(variant)

        price = data.get('price')
        if price is None and variants:
            price = variants[0].price

        # Get images - prefer network-captured over extracted
        images = data.get('images', [])
        if page_data and page_data.image_urls:
            network_images = self._filter_product_images(page_data.image_urls, url)
            if len(network_images) > len(images):
                images = network_images

        # LLM fallback: if no images found, ask LLM to pick from all captured URLs
        if not images and page_data and page_data.image_urls and self.llm:
            all_urls = page_data.image_urls[:50]  # cap to avoid huge prompts
            if all_urls:
                product_name = data.get('title') or data.get('name') or ''
                llm_result = self.llm.call(
                    prompt=(
                        f"Product: {product_name}\n"
                        f"Page: {url}\n\n"
                        f"These image URLs were loaded on this product page. "
                        f"Return ONLY the URLs that are actual product photos (not icons, logos, tracking pixels, UI elements, or banners). "
                        f"Return one URL per line, nothing else.\n\n"
                        + "\n".join(all_urls)
                    ),
                    expected_format="text",
                    max_tokens=2000,
                    operation="image_filter",
                )
                if llm_result.get("success") and llm_result.get("data"):
                    llm_text = llm_result["data"] if isinstance(llm_result["data"], str) else str(llm_result["data"])
                    images = [line.strip() for line in llm_text.strip().split('\n')
                              if line.strip().startswith('http')]
                    if images:
                        print(f"    [dom_fallback] LLM image fallback found {len(images)} images")

        # Also try HTML if still no images and we have the page HTML
        if not images and page_data and page_data.html:
            images = self._find_images(page_data.html)

        return self._create_product(
            name=data.get('title') or data.get('name'),
            price=price,
            currency=data.get('currency', 'USD'),
            images=images,
            description=data.get('description', ''),
            url=url,
            variants=variants,
            brand=data.get('brand') or self._infer_brand_from_url(url),
            sku=data.get('sku'),
            category=data.get('category'),
            raw_data=data,
        )

    def _load_patterns(self, domain: str) -> Optional[Dict[str, Any]]:
        """Load saved patterns for domain."""
        path = self.patterns_dir / f"{domain.replace('.', '_')}.json"
        if path.exists():
            try:
                with open(path) as f:
                    return json.load(f)
            except:
                pass
        return None

    def _save_patterns(self, domain: str, patterns: Dict[str, Any]):
        """Save patterns for domain."""
        path = self.patterns_dir / f"{domain.replace('.', '_')}.json"
        with open(path, 'w') as f:
            json.dump(patterns, f, indent=2)

    def _save_debug(self, domain: str, slug: str, llm_input: str, llm_response: str,
                    patterns: Dict[str, Any], matching_scripts: List[str],
                    llm_identified: Optional[Dict[str, str]] = None):
        """Save debug file showing LLM input, output, and matched locations."""
        if not self.debug:
            return

        debug_path = self.debug_dir / f"{domain.replace('.', '_')}_debug.txt"

        lines = []
        lines.append("=" * 80)
        lines.append("DOM_FALLBACK DEBUG OUTPUT")
        lines.append(f"Domain: {domain}")
        lines.append(f"Slug: {slug}")
        lines.append(f"Matching scripts: {len(matching_scripts)}")
        lines.append(f"Total filtered size: {len(llm_input):,} chars")
        lines.append("=" * 80)

        # Section 1: LLM Response
        lines.append("\n" + "=" * 80)
        lines.append("SECTION 1: LLM RESPONSE (what the LLM identified)")
        lines.append("=" * 80)
        lines.append(llm_response)

        # Section 2: Parsed identifications with highlights
        lines.append("\n" + "=" * 80)
        lines.append("SECTION 2: PARSED IDENTIFICATIONS (highlighted in scripts)")
        lines.append("=" * 80)
        if llm_identified:
            for key, value in llm_identified.items():
                lines.append(f"\n--- {key} ---")
                lines.append(f"LLM returned: {value[:300]}..." if len(value) > 300 else f"LLM returned: {value}")

                # Find where this appears in the filtered content
                idx = llm_input.find(value)
                if idx != -1:
                    # Show context around the match
                    start = max(0, idx - 150)
                    end = min(len(llm_input), idx + len(value) + 150)
                    context = llm_input[start:end]

                    # Highlight the match
                    match_start = idx - start
                    match_end = match_start + len(value)
                    highlighted = (
                        context[:match_start] +
                        "\n>>> MATCH START >>>\n" +
                        context[match_start:match_end] +
                        "\n<<< MATCH END <<<\n" +
                        context[match_end:]
                    )
                    lines.append(f"FOUND at char {idx}:")
                    lines.append(highlighted)
                else:
                    lines.append("NOT FOUND in filtered scripts!")

        # Section 3: Generated patterns - show ALL matches
        lines.append("\n" + "=" * 80)
        lines.append("SECTION 3: GENERATED REGEX PATTERNS (ALL MATCHES)")
        lines.append("=" * 80)
        if patterns:
            for field, pattern in patterns.items():
                lines.append(f"\n{field}: {pattern}")
                # Find ALL matches
                all_matches = list(re.finditer(pattern, llm_input))
                if all_matches:
                    lines.append(f"  Found {len(all_matches)} matches:")
                    for i, match in enumerate(all_matches):
                        captured = match.group(1)
                        start_pos = match.start()
                        # Show context around match
                        context_start = max(0, start_pos - 50)
                        context_end = min(len(llm_input), match.end() + 50)
                        context = llm_input[context_start:context_end]
                        lines.append(f"\n  Match {i+1} at pos {start_pos}:")
                        lines.append(f"    Captured: {captured[:100]}..." if len(captured) > 100 else f"    Captured: {captured}")
                        lines.append(f"    Context: ...{context}...")
                else:
                    lines.append(f"  ✗ Pattern does NOT match!")
        else:
            lines.append("(No patterns generated)")

        # Section 4: Filtered scripts (LLM input)
        lines.append("\n" + "=" * 80)
        lines.append("SECTION 4: FILTERED SCRIPTS (sent to LLM)")
        lines.append(f"Number of scripts: {len(matching_scripts)}")
        lines.append(f"Total length: {len(llm_input):,} chars")
        lines.append("=" * 80)

        for i, script in enumerate(matching_scripts):
            lines.append(f"\n--- SCRIPT {i+1} ({len(script):,} chars) ---")
            # Show script with slug occurrences highlighted
            if slug:
                # Build fuzzy pattern for highlighting
                words = re.split(r'[-_\s]+', slug)
                fuzzy_pattern = r'(' + r'[-_\s]?'.join(re.escape(word) for word in words) + r')'
                highlighted_script = re.sub(
                    fuzzy_pattern,
                    r'>>>\1<<<',
                    script,
                    flags=re.IGNORECASE
                )
                lines.append(highlighted_script)
            else:
                lines.append(script)

        with open(debug_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        print(f"    [dom_fallback] Debug saved to: {debug_path}")
