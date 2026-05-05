"""
Agent Registry
Initialize and register all agents with the agent manager
"""

import logging
from .agent_manager import get_agent_manager
from .database_agent import DatabaseAgent
from .excel_agent import ExcelAgent
from .email_agent import EmailAgent
from .report_agent import ReportAgent

logger = logging.getLogger(__name__)


def initialize_agents():
    """
    Initialize and register all agents
    
    This function should be called at application startup
    to register all available agents with the agent manager.
    
    To add a new agent:
    1. Create agent class inheriting from BaseAgent
    2. Implement can_handle(), process(), and get_capabilities()
    3. Import it here
    4. Add registration code below
    """
    manager = get_agent_manager()
    
    # Register Database Agent (highest priority - handles database queries)
    logger.info("Registering Database Agent...")
    database_agent = DatabaseAgent()
    manager.register_agent(database_agent)
    
    # Register Excel Agent
    logger.info("Registering Excel Agent...")
    excel_agent = ExcelAgent()
    manager.register_agent(excel_agent)
    
    # Register Email Agent
    logger.info("Registering Email Agent...")
    email_agent = EmailAgent()
    manager.register_agent(email_agent)
    
    # Register Report Agent
    logger.info("Registering Report Agent...")
    report_agent = ReportAgent()
    manager.register_agent(report_agent)
    
    # TODO: Add more agents as they are implemented
    # Example:
    # analytics_agent = AnalyticsAgent()
    # manager.register_agent(analytics_agent)
    
    logger.info(f"Successfully registered {len(manager.list_agents())} agents")
    logger.info(f"Agent stats: {manager.get_stats()}")
    
    return manager


def get_initialized_manager():
    """
    Get agent manager with all agents initialized
    
    Returns:
        AgentManager: Initialized manager instance
    """
    manager = get_agent_manager()
    
    # Initialize if no agents registered
    if len(manager.list_agents()) == 0:
        logger.info("No agents registered, initializing...")
        initialize_agents()
    
    return manager

