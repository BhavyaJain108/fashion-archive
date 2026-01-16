#!/usr/bin/env python3
"""
Modular LLM Interface for Fashion Archive System
Supports multiple LLM providers with unified API
"""

import os
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Load .env from config directory
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, '..', '..', '..'))
env_path = os.path.join(project_root, 'config', '.env')
load_dotenv(env_path)


class LLMInterface(ABC):
    """Abstract base class for LLM providers"""

    @abstractmethod
    def generate(self, prompt: str, max_tokens: int = 1000, temperature: float = 0.0) -> str:
        """Generate text response from prompt"""
        pass

    def get_last_usage(self) -> Optional[Dict[str, int]]:
        """Return token usage from last call: {input_tokens, output_tokens}"""
        return getattr(self, '_last_usage', None)


class ClaudeInterface(LLMInterface):
    """Anthropic Claude interface"""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        try:
            from anthropic import Anthropic
            self.api_key = api_key or os.getenv('CLAUDE_API_KEY') or os.getenv('ANTHROPIC_API_KEY')
            if not self.api_key:
                raise ValueError("Claude API key not found")
            self.client = Anthropic(api_key=self.api_key)
            self.model = model or os.getenv('CLAUDE_MODEL', 'claude-sonnet-4-20250514')
            self._last_usage = None
        except ImportError:
            raise ImportError("anthropic package not installed. Run: pip install anthropic")
    
    def generate(self, prompt: str, max_tokens: int = 1000, temperature: float = 0.0, response_model=None, debug: bool = False) -> str:
        if response_model:
            # Use structured output with tools
            schema = response_model.model_json_schema()

            if debug:
                print(f"🔍 DEBUG: Calling Claude API with structured output")
                print(f"   Model: {self.model}")
                print(f"   Max tokens: {max_tokens}")
                print(f"   Prompt length: {len(prompt)} chars (~{len(prompt)//4} tokens)")
                print(f"   Schema fields: {list(schema.get('properties', {}).keys())}")
                print(f"   Schema required: {schema.get('required', [])}")

            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
                tool_choice={"type": "tool", "name": "structured_output"},
                tools=[{
                    "name": "structured_output",
                    "description": "Return structured data matching the schema",
                    "input_schema": schema
                }]
            )

            # Capture token usage
            if hasattr(response, 'usage'):
                self._last_usage = {
                    'input_tokens': response.usage.input_tokens,
                    'output_tokens': response.usage.output_tokens
                }

            if debug:
                print(f"🔍 DEBUG: Response received")
                print(f"   Content blocks: {len(response.content) if response.content else 0}")
                if response.content:
                    for i, block in enumerate(response.content):
                        print(f"   Block {i}: type={getattr(block, 'type', 'unknown')}")

            # Extract structured data from tool use
            if response.content and len(response.content) > 0:
                for content_block in response.content:
                    # Check if this is a ToolUseBlock (has type='tool_use')
                    if hasattr(content_block, 'type') and content_block.type == 'tool_use':
                        if hasattr(content_block, 'input'):
                            tool_input = content_block.input

                            if debug:
                                print(f"🔍 DEBUG: Tool input received")
                                print(f"   Type: {type(tool_input)}")
                                print(f"   Keys: {list(tool_input.keys()) if isinstance(tool_input, dict) else 'not a dict'}")
                                print(f"   Empty: {not tool_input or tool_input == {}}")
                                if tool_input:
                                    import json
                                    print(f"   Content preview: {json.dumps(tool_input, indent=2)[:500]}")

                            return tool_input
                    elif hasattr(content_block, 'type') and content_block.type == 'text':
                        # Check if there's text content (might indicate refusal or explanation)
                        if debug:
                            print(f"🔍 DEBUG: Text block found: {content_block.text[:200]}")

            if debug:
                print(f"🔍 DEBUG: No tool use block found in response")
                print(f"   Response object: {response}")
                print(f"   Stop reason: {getattr(response, 'stop_reason', 'unknown')}")
                print(f"   Usage: {getattr(response, 'usage', 'unknown')}")

            raise ValueError("No structured output received from API")
        else:
            # Regular text generation
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}]
            )
            # Capture token usage
            if hasattr(response, 'usage'):
                self._last_usage = {
                    'input_tokens': response.usage.input_tokens,
                    'output_tokens': response.usage.output_tokens
                }
            return response.content[0].text.strip()


class OpenAIInterface(LLMInterface):
    """OpenAI GPT interface"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4"):
        try:
            import openai
            self.api_key = api_key or os.getenv('OPENAI_API_KEY')
            if not self.api_key:
                raise ValueError("OpenAI API key not found")
            self.client = openai.OpenAI(api_key=self.api_key)
            self.model = model
        except ImportError:
            raise ImportError("openai package not installed. Run: pip install openai")
    
    def generate(self, prompt: str, max_tokens: int = 1000, temperature: float = 0.0) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content.strip()


class LocalLLMInterface(LLMInterface):
    """Local LLM interface (via Ollama, LM Studio, etc.)"""
    
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3"):
        try:
            import requests
            self.base_url = base_url.rstrip('/')
            self.model = model
            self.session = requests.Session()
        except ImportError:
            raise ImportError("requests package not installed")
    
    def generate(self, prompt: str, max_tokens: int = 1000, temperature: float = 0.0) -> str:
        try:
            response = self.session.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens
                    }
                },
                timeout=30
            )
            response.raise_for_status()
            return response.json()["response"].strip()
        except Exception as e:
            raise RuntimeError(f"Local LLM request failed: {e}")


def get_llm_client(provider: Optional[str] = None) -> LLMInterface:
    """Factory function to get LLM client based on configuration"""
    
    provider = provider or os.getenv('LLM_PROVIDER', 'claude').lower()
    
    if provider == 'claude':
        model = os.getenv('CLAUDE_MODEL', 'claude-3-5-sonnet-20241022')
        return ClaudeInterface(model=model)
    elif provider == 'openai':
        model = os.getenv('OPENAI_MODEL', 'gpt-4')
        return OpenAIInterface(model=model)
    elif provider == 'local':
        base_url = os.getenv('LOCAL_LLM_URL', 'http://localhost:11434')
        model = os.getenv('LOCAL_LLM_MODEL', 'llama3')
        return LocalLLMInterface(base_url=base_url, model=model)
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")


# Convenience function for backwards compatibility
def create_llm_client() -> LLMInterface:
    """Create LLM client with current configuration"""
    return get_llm_client()