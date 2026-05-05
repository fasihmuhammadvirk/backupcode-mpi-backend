"""
Base Agent Interface
All agents must inherit from this base class for consistency
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class AgentCapability(Enum):
    """Agent capabilities for routing"""
    QUERY_DATABASE = "query_database"
    GENERATE_EXCEL = "generate_excel"
    SEND_EMAIL = "send_email"
    GENERATE_REPORT = "generate_report"
    ANALYZE_DATA = "analyze_data"
    MANAGE_INVOICES = "manage_invoices"
    MANAGE_MAPPINGS = "manage_mappings"


class AgentPriority(Enum):
    """Agent priority levels"""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class BaseAgent(ABC):
    """
    Base class for all agents in the system
    
    All agents must implement:
    - can_handle(): Check if agent can handle a request
    - process(): Process the request and return response
    - get_capabilities(): List of capabilities this agent supports
    """
    
    def __init__(self, agent_name: str, priority: AgentPriority = AgentPriority.MEDIUM):
        """
        Initialize base agent
        
        Args:
            agent_name: Unique name for this agent
            priority: Priority level for agent selection
        """
        self.agent_name = agent_name
        self.priority = priority
        self.enabled = True
        logger.info(f"Initialized agent: {agent_name} with priority {priority.name}")
    
    @abstractmethod
    def can_handle(self, request: Dict[str, Any]) -> bool:
        """
        Determine if this agent can handle the request
        
        Args:
            request: Request dictionary containing:
                - question: str - User's question/request
                - intent: str - Classified intent (optional)
                - context: Dict - Additional context (optional)
                
        Returns:
            bool: True if agent can handle this request
        """
        pass
    
    @abstractmethod
    async def process(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process the request and return response
        
        Args:
            request: Request dictionary
            
        Returns:
            Dict containing:
                - success: bool - Whether request was successful
                - data: Any - Response data
                - error: Optional[str] - Error message if failed
                - metadata: Dict - Additional metadata
        """
        pass
    
    @abstractmethod
    def get_capabilities(self) -> List[AgentCapability]:
        """
        Get list of capabilities this agent supports
        
        Returns:
            List of AgentCapability enums
        """
        pass
    
    def get_info(self) -> Dict[str, Any]:
        """
        Get agent information
        
        Returns:
            Dict with agent metadata
        """
        return {
            "name": self.agent_name,
            "priority": self.priority.name,
            "enabled": self.enabled,
            "capabilities": [cap.value for cap in self.get_capabilities()]
        }
    
    def enable(self):
        """Enable this agent"""
        self.enabled = True
        logger.info(f"Agent {self.agent_name} enabled")
    
    def disable(self):
        """Disable this agent"""
        self.enabled = False
        logger.info(f"Agent {self.agent_name} disabled")
    
    def validate_request(self, request: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate request format
        
        Args:
            request: Request to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not isinstance(request, dict):
            return False, "Request must be a dictionary"
        
        if "question" not in request:
            return False, "Request must contain 'question' field"
        
        if not isinstance(request["question"], str):
            return False, "Question must be a string"
        
        if len(request["question"].strip()) == 0:
            return False, "Question cannot be empty"
        
        return True, None

