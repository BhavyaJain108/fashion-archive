#!/usr/bin/env python3

from typing import TypedDict, List, Dict, Any
from dataclasses import dataclass
from enum import Enum
import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
import time
import random

from langgraph.graph import StateGraph, START, END
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_interface import get_llm_client
from agentic_research.fashion_web_scraper import FashionWebScraper

class ConsensusStatus(Enum):
    PROPOSING = "proposing"
    AGREED = "agreed"
    FAILED = "failed"

@dataclass
class AgentProposal:
    agent_id: str
    tasks_claimed: List[str]
    reasoning: str
    confidence: float

class ResearchState(TypedDict):
    # Input
    collection_query: str
    
    # Agent coordination
    agent_proposals: Dict[str, AgentProposal]
    consensus_status: ConsensusStatus
    agreed_assignments: Dict[str, List[str]]
    
    # Research results
    research_findings: Dict[str, Dict[str, Any]]
    final_synthesis: Dict[str, Any]

class SimpleResearchAgent:
    def __init__(self, agent_id: str, personality: str, specialties: List[str]):
        self.agent_id = agent_id
        self.personality = personality
        self.specialties = specialties
        self.llm = get_llm_client()
        self.scraper = FashionWebScraper()
    
    def propose_tasks(self, available_tasks: List[str], query: str) -> AgentProposal:
        """Agent decides what they want to research"""
        
        # Simple task claiming based on specialties
        claimed_tasks = []
        for task in available_tasks:
            if any(specialty in task.lower() for specialty in self.specialties):
                claimed_tasks.append(task)
        
        if not claimed_tasks:
            # Fallback - claim first available task
            claimed_tasks = [available_tasks[0]] if available_tasks else []
        
        return AgentProposal(
            agent_id=self.agent_id,
            tasks_claimed=claimed_tasks,
            reasoning=f"I specialize in {', '.join(self.specialties)} and can handle {', '.join(claimed_tasks)}",
            confidence=0.8
        )
    
    def research(self, tasks: List[str], query: str) -> Dict[str, Any]:
        """Perform actual research"""
        
        findings = {}
        
        for task in tasks:
            if task == "brand_history":
                findings[task] = self._research_brand_history(query)
            elif task == "materials":
                findings[task] = self._research_materials(query)
            elif task == "aesthetic_analysis":
                findings[task] = self._research_aesthetics(query)
        
        # Collect real sources from research
        real_sources = []
        for task in tasks:
            if hasattr(self, f'_last_sources_{task}'):
                real_sources.extend(getattr(self, f'_last_sources_{task}'))
        
        if not real_sources:
            real_sources = ["No web sources found"]
        
        return {
            "agent_id": self.agent_id,
            "findings": findings,
            "confidence": random.uniform(0.7, 0.9),
            "sources": real_sources[:3]  # Limit to top 3 sources
        }
    
    def _research_brand_history(self, query: str) -> str:
        """Research brand history using web scraping + LLM analysis"""
        
        print(f"    🌐 {self.agent_id} scraping web for: {query}")
        
        # Step 1: Get web content
        try:
            web_results = self.scraper.scrape_collection_info(query)
            web_content = web_results.get('content_summary', '')
            sources = [s.get('url', 'unknown') for s in web_results.get('sources', [])]
        except Exception as e:
            print(f"    ⚠️ Web scraping failed: {e}")
            web_content = ""
            sources = []
        
        # Step 2: Combine web content with LLM knowledge
        if web_content:
            prompt = f"""Based on the following web content about "{query}", provide 2-3 key historical facts about the brand/designer and collection:

Web Content:
{web_content[:1000]}

Please focus on historical context, brand background, and designer information."""
        else:
            prompt = f"Provide 2-3 key historical facts about the fashion brand/designer mentioned in: {query}"
        
        try:
            response = self.llm.generate(prompt, max_tokens=300)
            
            # Store sources for later use
            self._last_sources_brand_history = sources
            
            return response
        except Exception as e:
            print(f"    ❌ LLM error for historian: {e}")
            self._last_sources_brand_history = []
            return f"Historical context research for {query} - limited data available"
    
    def _research_materials(self, query: str) -> str:
        """Research materials using web scraping + LLM analysis"""
        
        print(f"    🌐 {self.agent_id} scraping web for materials info: {query}")
        
        # Step 1: Get web content focused on materials
        try:
            materials_query = f"{query} materials fabrics sustainability"
            web_results = self.scraper.search_fashion_content(materials_query)
            web_content = ' '.join([r.get('content', '') for r in web_results])
            sources = [r.get('url', 'unknown') for r in web_results]
        except Exception as e:
            print(f"    ⚠️ Web scraping failed: {e}")
            web_content = ""
            sources = []
        
        # Step 2: Analyze with LLM
        if web_content:
            prompt = f"""Based on this web content about "{query}", analyze the materials, fabrics, and sustainability practices:

Web Content:
{web_content[:1000]}

Focus on: materials used, fabric innovations, sustainability initiatives, craftsmanship techniques."""
        else:
            prompt = f"What materials, fabrics, or sustainability practices might be relevant to: {query}"
        
        try:
            response = self.llm.generate(prompt, max_tokens=300)
            
            # Store sources for later use
            self._last_sources_materials = sources
            
            return response
        except Exception as e:
            print(f"    ❌ LLM error for materialist: {e}")
            self._last_sources_materials = []
            return f"Materials analysis for {query} - limited data available"
    
    def _research_aesthetics(self, query: str) -> str:
        """Research aesthetics using web scraping + LLM analysis"""
        
        print(f"    🌐 {self.agent_id} scraping web for aesthetic info: {query}")
        
        # Step 1: Get web content focused on aesthetics
        try:
            aesthetic_query = f"{query} aesthetic visual style inspiration theme"
            web_results = self.scraper.search_fashion_content(aesthetic_query)
            web_content = ' '.join([r.get('content', '') for r in web_results])
            sources = [r.get('url', 'unknown') for r in web_results]
        except Exception as e:
            print(f"    ⚠️ Web scraping failed: {e}")
            web_content = ""
            sources = []
        
        # Step 2: Analyze with LLM
        if web_content:
            prompt = f"""Based on this web content about "{query}", analyze the visual and cultural themes:

Web Content:
{web_content[:1000]}

Focus on: visual aesthetics, cultural references, artistic influences, styling choices, color palettes."""
        else:
            prompt = f"Analyze the visual and cultural themes that might be present in: {query}"
        
        try:
            response = self.llm.generate(prompt, max_tokens=300)
            
            # Store sources for later use
            self._last_sources_aesthetic_analysis = sources
            
            return response
        except Exception as e:
            print(f"    ❌ LLM error for aesthete: {e}")
            self._last_sources_aesthetic_analysis = []
            return f"Aesthetic analysis for {query} - limited data available"

class SimpleResearchSystem:
    def __init__(self):
        # Create our three simple agents
        self.agents = {
            "historian": SimpleResearchAgent(
                "historian", 
                "methodical and context-focused",
                ["history", "brand", "background", "archive"]
            ),
            "materialist": SimpleResearchAgent(
                "materialist",
                "technical and detail-oriented", 
                ["materials", "fabric", "sustainable", "technical"]
            ),
            "aesthete": SimpleResearchAgent(
                "aesthete",
                "visual and cultural analysis",
                ["aesthetic", "visual", "culture", "theme", "style"]
            )
        }
        
        # Available research tasks
        self.available_tasks = [
            "brand_history",
            "materials", 
            "aesthetic_analysis"
        ]
        
        self.research_graph = self._create_research_graph()
    
    def _create_research_graph(self):
        """Create the LangGraph research workflow"""
        
        graph = StateGraph(ResearchState)
        
        # Add nodes
        graph.add_node("collect_proposals", self._collect_proposals_node)
        graph.add_node("negotiate_consensus", self._negotiate_consensus_node)
        graph.add_node("execute_research", self._execute_research_node)
        graph.add_node("synthesize_results", self._synthesize_results_node)
        
        # Add edges
        graph.add_edge(START, "collect_proposals")
        graph.add_edge("collect_proposals", "negotiate_consensus")
        
        # Conditional routing based on consensus
        graph.add_conditional_edges(
            "negotiate_consensus",
            self._consensus_routing,
            {
                "agreed": "execute_research",
                "failed": END
            }
        )
        
        graph.add_edge("execute_research", "synthesize_results")
        graph.add_edge("synthesize_results", END)
        
        return graph.compile()
    
    def _collect_proposals_node(self, state: ResearchState) -> ResearchState:
        """Each agent proposes what they want to research"""
        
        print(f"🤔 Agents proposing research tasks for: {state['collection_query']}")
        
        proposals = {}
        
        for agent_id, agent in self.agents.items():
            proposal = agent.propose_tasks(self.available_tasks, state["collection_query"])
            proposals[agent_id] = proposal
            print(f"  {agent_id}: {proposal.reasoning}")
        
        state["agent_proposals"] = proposals
        state["consensus_status"] = ConsensusStatus.PROPOSING
        
        return state
    
    def _negotiate_consensus_node(self, state: ResearchState) -> ResearchState:
        """Simple consensus - just assign tasks to avoid conflicts"""
        
        print("🤝 Negotiating task assignments...")
        
        proposals = state["agent_proposals"]
        assignments = {}
        
        # Simple assignment: each agent gets their first claimed task
        used_tasks = set()
        
        for agent_id, proposal in proposals.items():
            available_tasks = [task for task in proposal.tasks_claimed if task not in used_tasks]
            if available_tasks:
                assignments[agent_id] = [available_tasks[0]]
                used_tasks.add(available_tasks[0])
                print(f"  ✅ {agent_id} assigned: {available_tasks[0]}")
            else:
                assignments[agent_id] = []
                print(f"  ❌ {agent_id} got no tasks (conflicts)")
        
        state["agreed_assignments"] = assignments
        state["consensus_status"] = ConsensusStatus.AGREED
        
        return state
    
    def _consensus_routing(self, state: ResearchState) -> str:
        """Route based on consensus status"""
        if state["consensus_status"] == ConsensusStatus.AGREED:
            return "agreed"
        else:
            return "failed"
    
    def _execute_research_node(self, state: ResearchState) -> ResearchState:
        """Agents perform their assigned research"""
        
        print("🔍 Executing research tasks...")
        
        research_findings = {}
        assignments = state["agreed_assignments"]
        
        for agent_id, tasks in assignments.items():
            if tasks:  # Only if agent has tasks
                print(f"  {agent_id} researching: {', '.join(tasks)}")
                agent = self.agents[agent_id]
                findings = agent.research(tasks, state["collection_query"])
                research_findings[agent_id] = findings
        
        state["research_findings"] = research_findings
        return state
    
    def _synthesize_results_node(self, state: ResearchState) -> ResearchState:
        """Combine all research findings"""
        
        print("📝 Synthesizing research results...")
        
        findings = state["research_findings"]
        
        synthesis = {
            "query": state["collection_query"],
            "research_summary": {},
            "total_agents": len(findings),
            "timestamp": datetime.now().isoformat()
        }
        
        # Combine findings from all agents
        for agent_id, agent_findings in findings.items():
            synthesis["research_summary"][agent_id] = {
                "findings": agent_findings["findings"],
                "confidence": agent_findings["confidence"],
                "sources": agent_findings["sources"]
            }
        
        state["final_synthesis"] = synthesis
        print("✅ Research synthesis complete!")
        
        return state
    
    def research_collection(self, collection_query: str) -> Dict[str, Any]:
        """Main entry point for research"""
        
        print(f"\n🎯 Starting research for: {collection_query}")
        print("=" * 50)
        
        initial_state = ResearchState(
            collection_query=collection_query,
            agent_proposals={},
            consensus_status=ConsensusStatus.PROPOSING,
            agreed_assignments={},
            research_findings={},
            final_synthesis={}
        )
        
        # Run the research graph
        final_state = self.research_graph.invoke(initial_state)
        
        print("=" * 50)
        return final_state["final_synthesis"]

def test_simple_research():
    """Test the simple research system"""
    
    research_system = SimpleResearchSystem()
    
    # Test with a simple query
    result = research_system.research_collection("Chanel Fall 2025 Couture")
    
    print("\n📊 FINAL RESEARCH RESULTS:")
    print("=" * 50)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    test_simple_research()