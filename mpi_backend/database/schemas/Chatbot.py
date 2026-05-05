"""
Chatbot Schema Models
Contains all Pydantic models for chatbot request/response validation
"""

from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """Model for a single chat message"""
    role: str = Field(
        ...,
        description="Role of the message sender: 'user' or 'assistant'",
        example="user"
    )
    content: str = Field(
        ...,
        description="Content of the message",
        example="Show me all invoices from BMW Plumbing Supplies"
    )


class QueryRequest(BaseModel):
    """Request model for natural language queries"""
    question: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Natural language question about the database",
        example="Show me all invoices from BMW Plumbing Supplies in July"
    )
    session_id: Optional[str] = Field(
        None,
        description="Optional session ID for maintaining conversation context",
        example=None
    )
    message_history: Optional[List[ChatMessage]] = Field(
        None,
        description="Optional list of previous messages for conversation context (last 12 messages recommended)",
        example=None
    )

    class Config:
        from_attributes = True


class QueryResponse(BaseModel):
    """Response model for query results with enhanced metadata"""
    answer: str = Field(
        ...,
        description="Natural language answer to the question (formatted in Markdown)"
    )
    error: Optional[str] = Field(
        None,
        description="Error message if any"
    )
    intent: Optional[str] = Field(
        None,
        description="Classified intent of the query (greeting, database_query, help, etc.)"
    )
    is_conversational: Optional[bool] = Field(
        False,
        description="Whether this is a conversational response (vs database query)"
    )
    formatting: Optional[Dict[str, Any]] = Field(
        None,
        description="Metadata about response formatting (markdown, tables, etc.)"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="Additional metadata about the response"
    )

    class Config:
        from_attributes = True


class AgentInfo(BaseModel):
    """Model for agent information"""
    name: str = Field(..., description="Agent name")
    capabilities: List[str] = Field(
        default_factory=list,
        description="List of agent capabilities"
    )
    description: Optional[str] = Field(
        None,
        description="Agent description"
    )

    class Config:
        from_attributes = True


class AgentStats(BaseModel):
    """Model for agent statistics"""
    total_requests: int = Field(default=0, description="Total requests processed")
    successful_requests: int = Field(
        default=0,
        description="Number of successful requests"
    )
    failed_requests: int = Field(default=0, description="Number of failed requests")
    agent_distribution: Dict[str, int] = Field(
        default_factory=dict,
        description="Distribution of requests by agent"
    )

    class Config:
        from_attributes = True


class AgentInfoResponse(BaseModel):
    """Response model for agent information"""
    mode: str = Field(
        ...,
        description="Current mode (multi_agent or legacy)"
    )
    agents: List[AgentInfo] = Field(
        default_factory=list,
        description="List of registered agents"
    )
    stats: Optional[AgentStats] = Field(
        None,
        description="Agent statistics"
    )
    error: Optional[str] = Field(
        None,
        description="Error message if any"
    )

    class Config:
        from_attributes = True
