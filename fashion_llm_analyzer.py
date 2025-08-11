#!/usr/bin/env python3
"""
Fashion Look Analyzer using Claude API
Analyzes runway looks and provides detailed fashion insights
"""

import os
import base64
import requests
from pathlib import Path
from typing import Dict, Optional


class FashionLookAnalyzer:
    """Analyzes fashion runway looks using Claude API."""
    
    def __init__(self, config_file: str = ".config"):
        self.api_key = self._load_api_key(config_file)
        self.api_url = "https://api.anthropic.com/v1/messages"
        
    def _load_api_key(self, config_file: str) -> str:
        """Load Claude API key from config file."""
        config_path = Path(config_file)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_file}")
            
        with open(config_path, 'r') as f:
            for line in f:
                if line.startswith('CLAUDE_API_KEY='):
                    return line.split('=', 1)[1].strip()
        
        raise ValueError("CLAUDE_API_KEY not found in config file")
    
    def encode_image(self, image_path: str) -> str:
        """Encode image to base64 for API."""
        with open(image_path, 'rb') as f:
            return base64.b64encode(f.read()).decode('utf-8')
    
    def extract_look_number(self, filename: str) -> str:
        """Extract look number from filename."""
        import re
        # Look for patterns like "001", "002", etc. at the end of filename
        match = re.search(r'(\d{3})\.jpg$', filename.lower())
        if match:
            return match.group(1).lstrip('0') or '0'  # Remove leading zeros
        return "1"  # Default to look 1
    
    def analyze_look_from_title(self, image_path: str, collection_info: Dict[str, str] = None) -> Dict[str, str]:
        """
        Analyze a runway look based on filename/title only using Claude API.
        
        Args:
            image_path: Path to the runway image (used for filename)
            collection_info: Optional dict with designer, season, year info
            
        Returns:
            Dict with analysis results
        """
        # Get filename for analysis
        filename = Path(image_path).name
        
        # Build context from collection info
        context = ""
        if collection_info:
            designer = collection_info.get('designer', '')
            season = collection_info.get('season', '')
            year = collection_info.get('year', '')
            context = f"This is from {designer} {season} {year} collection. "
        
        # Extract look number from filename
        look_number = self.extract_look_number(filename)
        
        # Create prompt for specific look analysis
        prompt = f"""{context}I'm analyzing Look #{look_number} from this runway collection. 

Based on your knowledge of the designer's aesthetic and typical runway show structure, provide a detailed analysis of what this specific look might feature:

1. **Look Position Analysis**: What is the significance of Look #{look_number} in a typical runway show? (Is this likely an opening look, mid-show statement, or finale piece?)

2. **Expected Styling**: Based on the designer's signature style, what type of garments, silhouettes, and overall aesthetic would be expected for this look?

3. **Design Philosophy**: How would this look typically embody the designer's creative vision and brand identity?

4. **Runway Storytelling**: What role does Look #{look_number} play in the overall narrative of a fashion show?

5. **Fashion Elements**: What specific design elements, styling choices, or fashion details might characterize this look?

Please provide professional fashion commentary as if analyzing a runway presentation. Focus on the designer's established aesthetic and typical show structure."""

        # Prepare API request
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01"
        }
        
        payload = {
            "model": "claude-3-5-sonnet-20241022",
            "max_tokens": 1000,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]
        }
        
        try:
            print(f"Making API request to: {self.api_url}")
            print(f"API Key starts with: {self.api_key[:20]}...")
            
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=30)
            
            print(f"Response status: {response.status_code}")
            print(f"Response headers: {dict(response.headers)}")
            
            if response.status_code != 200:
                print(f"Response body: {response.text}")
                
            response.raise_for_status()
            
            result = response.json()
            analysis = result["content"][0]["text"]
            
            return {
                "success": True,
                "analysis": analysis,
                "image_path": image_path,
                "collection_info": collection_info
            }
            
        except requests.exceptions.RequestException as e:
            return {"error": f"API request failed: {str(e)}"}
        except Exception as e:
            return {"error": f"Analysis failed: {str(e)}"}


def test_analyzer():
    """Test the analyzer with AWGE 2026 look 1."""
    
    # Initialize analyzer
    analyzer = FashionLookAnalyzer()
    
    # Test image path (look 1 from AWGE collection)
    test_image = "downloads/002_AWGE-by-Asap-Rocky-Menswear-Spring-Summer-2026-Paris-Fashion-Week-Runway-001.jpg"
    
    # Collection info
    collection_info = {
        "designer": "AWGE by ASAP Rocky",
        "season": "Spring Summer",
        "year": "2026"
    }
    
    # Extract look number for display
    look_number = analyzer.extract_look_number(test_image)
    
    print(f"🔍 Analyzing AWGE Spring Summer 2026 - Look #{look_number}...")
    print(f"Image: {test_image}")
    print("=" * 80)
    
    # Analyze the specific look number
    result = analyzer.analyze_look_from_title(test_image, collection_info)
    
    if "error" in result:
        print(f"❌ Error: {result['error']}")
        return
    
    print("✅ Analysis Complete!")
    print("=" * 80)
    print(result["analysis"])
    print("=" * 80)


if __name__ == "__main__":
    test_analyzer()