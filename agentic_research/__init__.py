"""
Agentic Research System for Fashion Archive

This module provides a multi-agent research system that coordinates
fashion research across specialized AI agents using LangGraph.

Components:
- simple_research_agents.py: Core agent system with LangGraph coordination
- fashion_web_scraper.py: Web scraping module for fashion sources
- test_research_system.py: Interactive testing interface

Usage:
    from agentic_research.simple_research_agents import SimpleResearchSystem
    
    research_system = SimpleResearchSystem()
    results = research_system.research_collection("Chanel Fall 2025 Couture")
"""