"""
Agent Manager
Manages all agents and routes requests to appropriate handlers
"""

from typing import Dict, Any, Optional, List
import logging
from .base_agent import BaseAgent, AgentCapability, AgentPriority
from .intent_router import IntentRouter, RequestIntent

logger = logging.getLogger(__name__)


class AgentManager:
    """
    Central manager for all agents in the system
    Handles agent registration, routing, and orchestration
    """
    
    def __init__(self):
        """Initialize the agent manager"""
        self.agents: Dict[str, BaseAgent] = {}
        self.intent_router = IntentRouter()
        logger.info("AgentManager initialized")
    
    def register_agent(self, agent: BaseAgent) -> bool:
        """
        Register a new agent
        
        Args:
            agent: Agent instance to register
            
        Returns:
            bool: True if registered successfully
        """
        if not isinstance(agent, BaseAgent):
            logger.error(f"Cannot register {agent}: not a BaseAgent instance")
            return False
        
        if agent.agent_name in self.agents:
            logger.warning(f"Agent {agent.agent_name} already registered, replacing...")
        
        self.agents[agent.agent_name] = agent
        logger.info(f"Registered agent: {agent.agent_name} with capabilities: {[c.value for c in agent.get_capabilities()]}")
        return True
    
    def unregister_agent(self, agent_name: str) -> bool:
        """
        Unregister an agent
        
        Args:
            agent_name: Name of agent to unregister
            
        Returns:
            bool: True if unregistered successfully
        """
        if agent_name in self.agents:
            del self.agents[agent_name]
            logger.info(f"Unregistered agent: {agent_name}")
            return True
        
        logger.warning(f"Agent {agent_name} not found for unregistration")
        return False
    
    def get_agent(self, agent_name: str) -> Optional[BaseAgent]:
        """
        Get agent by name
        
        Args:
            agent_name: Name of agent to retrieve
            
        Returns:
            BaseAgent instance or None
        """
        return self.agents.get(agent_name)
    
    def list_agents(self) -> List[Dict[str, Any]]:
        """
        List all registered agents
        
        Returns:
            List of agent info dictionaries
        """
        return [agent.get_info() for agent in self.agents.values()]
    
    def find_capable_agents(self, capability: AgentCapability) -> List[BaseAgent]:
        """
        Find all agents with a specific capability
        
        Args:
            capability: Required capability
            
        Returns:
            List of capable agents, sorted by priority
        """
        capable = [
            agent for agent in self.agents.values()
            if capability in agent.get_capabilities() and agent.enabled
        ]
        
        # Sort by priority (highest first)
        capable.sort(key=lambda a: a.priority.value, reverse=True)
        
        return capable
    
    def select_agent(self, request: Dict[str, Any]) -> Optional[BaseAgent]:
        """
        Select the best agent to handle a request
        
        Args:
            request: Request dictionary
            
        Returns:
            Selected agent or None
        """
        # Get all agents that can handle this request
        candidates = [
            agent for agent in self.agents.values()
            if agent.enabled and agent.can_handle(request)
        ]
        
        if not candidates:
            logger.warning(f"No agent found to handle request: {request.get('question', '')[:50]}")
            return None
        
        # Sort by priority and select highest
        candidates.sort(key=lambda a: a.priority.value, reverse=True)
        selected = candidates[0]
        
        logger.info(f"Selected agent: {selected.agent_name} for request")
        return selected
    
    async def process_request(
        self,
        question: str,
        session_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        message_history: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Process a request by routing to appropriate agent
        
        Args:
            question: User's question
            session_id: Optional session ID
            context: Optional context
            message_history: Optional list of previous messages for conversation context
            
        Returns:
            Response dictionary
        """
        try:
            # Create standardized request with message history
            request = self.intent_router.create_request(
                question, session_id, context, message_history
            )
            
            logger.info(f"Processing request with intent: {request['intent']}")
            if message_history:
                logger.info(f"Message history contains {len(message_history)} messages")
            
            # Select appropriate agent
            agent = self.select_agent(request)
            
            if not agent:
                return {
                    "success": False,
                    "error": "No suitable agent found to handle this request",
                    "data": None,
                    "metadata": {
                        "intent": request["intent"],
                        "available_agents": [a.agent_name for a in self.agents.values()]
                    }
                }
            
            # Validate request
            is_valid, error_msg = agent.validate_request(request)
            if not is_valid:
                return {
                    "success": False,
                    "error": f"Invalid request: {error_msg}",
                    "data": None,
                    "metadata": {"agent": agent.agent_name}
                }
            
            # Process request
            logger.info(f"Routing to agent: {agent.agent_name}")
            response = await agent.process(request)
            
            # Add metadata
            if "metadata" not in response:
                response["metadata"] = {}
            
            response["metadata"]["agent"] = agent.agent_name
            response["metadata"]["intent"] = request["intent"]
            
            return response
            
        except Exception as e:
            logger.error(f"Error processing request: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Error processing request: {str(e)}",
                "data": None,
                "metadata": {}
            }
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get manager statistics
        
        Returns:
            Statistics dictionary
        """
        return {
            "total_agents": len(self.agents),
            "enabled_agents": len([a for a in self.agents.values() if a.enabled]),
            "disabled_agents": len([a for a in self.agents.values() if not a.enabled]),
            "agents_by_capability": self._group_by_capability()
        }
    
    def _group_by_capability(self) -> Dict[str, List[str]]:
        """Group agents by capability"""
        grouped = {}
        for agent in self.agents.values():
            for capability in agent.get_capabilities():
                cap_name = capability.value
                if cap_name not in grouped:
                    grouped[cap_name] = []
                grouped[cap_name].append(agent.agent_name)
        return grouped


# Global agent manager instance
_agent_manager: Optional[AgentManager] = None


def get_agent_manager() -> AgentManager:
    """
    Get or create the global agent manager instance (singleton)
    
    Returns:
        AgentManager instance
    """
    global _agent_manager
    if _agent_manager is None:
        _agent_manager = AgentManager()
        logger.info("Created global AgentManager instance")
    return _agent_manager

