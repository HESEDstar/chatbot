from typing import NotRequired, TypedDict, List, Annotated, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class AgentState(TypedDict):
    # Append-only list of messages (Chat History)
    messages: Annotated[List[BaseMessage], add_messages]
    
    # Context variables
    # user_id: NotRequired[Optional[str]]
    summary: NotRequired[Optional[str]]
    user_role: str  # 'student', 'teacher', 'admin', 'anonymous'
    # session_id: NotRequired[Optional[str]]

    # lead details for generate_lead tool   
    lead_name: NotRequired[Optional[str]]
    lead_role: NotRequired[Optional[str]]
    lead_school_name: NotRequired[Optional[str]]
    lead_email: NotRequired[Optional[str]]
    
    # Flags for frontend actions
    escalate: NotRequired[bool]
    lead_captured: NotRequired[Optional[bool]]
    # download_ready: NotRequired[Optional[bool]]
    # filename: NotRequired[Optional[str]]

class UserInformation(BaseModel):
    """Information to extract about the lead."""
    lead_name: str | None = Field(None, description="The lead first or full name.")
    lead_role: str | None = Field(None, description="The lead's job title or role (e.g., Teacher, Principal).")
    lead_school_name: str | None = Field(None, description="The name of the school or organization.")
    lead_email: str | None = Field(None, description="The lead's email address.")
    lead_pain_point: str | None = Field(None, description="The specific pain point the lead mentioned.")
    
