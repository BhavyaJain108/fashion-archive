#!/usr/bin/env python3
"""
Quick demo of the agentic research system
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_research.simple_research_agents import SimpleResearchSystem
import json

def demo_research():
    """Demo the research system with a few examples"""
    
    print("🎯 Agentic Research System Demo")
    print("=" * 50)
    
    research_system = SimpleResearchSystem()
    
    # Test queries
    queries = [
        "Valentino Ready To Wear Fall Winter 2014 Paris",
        "Issey Miyake Pleats Please Spring 2020"
    ]
    
    for query in queries:
        print(f"\n🔍 Researching: {query}")
        print("-" * 40)
        
        try:
            result = research_system.research_collection(query)
            
            print(f"\n📊 Results for: {result['query']}")
            print(f"Agents involved: {result['total_agents']}")
            
            # Show brief summary
            for agent_id, summary in result['research_summary'].items():
                print(f"\n{agent_id.upper()} (confidence: {summary['confidence']:.2f}):")
                for task, findings in summary['findings'].items():
                    preview = findings[:150] + "..." if len(findings) > 150 else findings
                    print(f"  {task}: {preview}")
            
            print("\n" + "=" * 50)
            
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    demo_research()