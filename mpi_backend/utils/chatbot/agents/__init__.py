"""
Agent system for MPI Backend
Provides scalable multi-agent architecture
"""

from .base_agent import BaseAgent, AgentCapability, AgentPriority
from .agent_manager import AgentManager, get_agent_manager
from .intent_router import IntentRouter, RequestIntent
from .registry import initialize_agents, get_initialized_manager
from .database_agent import DatabaseAgent
from .excel_agent import ExcelAgent
from .email_agent import EmailAgent
from .report_agent import ReportAgent

__all__ = [
    'BaseAgent',
    'AgentCapability',
    'AgentPriority',
    'AgentManager',
    'get_agent_manager',
    'IntentRouter',
    'RequestIntent',
    'initialize_agents',
    'get_initialized_manager',
    'DatabaseAgent',
    'ExcelAgent',
    'EmailAgent',
    'ReportAgent'
]
