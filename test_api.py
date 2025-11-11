#!/usr/bin/env python3

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Test Claude API
def test_claude_api():
    try:
        from anthropic import Anthropic
        
        api_key = os.getenv('CLAUDE_API_KEY') or os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            print("❌ No Claude API key found in environment")
            return False
            
        print(f"🔑 API key found: {api_key[:10]}...")
        
        client = Anthropic(api_key=api_key)
        
        # Simple test
        model = os.getenv('CLAUDE_MODEL', 'claude-3-5-sonnet-20241022')
        print(f"🤖 Using model: {model}")
        
        response = client.messages.create(
            model=model,
            max_tokens=50,
            messages=[{"role": "user", "content": "Say 'API test successful' in JSON format like {\"status\": \"success\", \"message\": \"API test successful\"}"}]
        )
        
        result = response.content[0].text.strip()
        print(f"✅ Claude API Response: {result}")
        return True
        
    except ImportError:
        print("❌ anthropic package not installed. Run: pip install anthropic")
        return False
    except Exception as e:
        print(f"❌ Claude API test failed: {e}")
        return False

if __name__ == "__main__":
    print("Testing Claude API...")
    success = test_claude_api()
    sys.exit(0 if success else 1)