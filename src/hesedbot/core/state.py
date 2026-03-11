from typing import NotRequired, TypedDict, List, Annotated, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages, RemoveMessage

class AgentState(TypedDict):
    # Append-only list of messages (Chat History)
    messages: Annotated[List[BaseMessage], add_messages]
    
    # Context variables
    user_id: NotRequired[Optional[str]]
    summary: NotRequired[Optional[str]]
    user_role: str  # 'student', 'teacher', 'admin', 'anonymous'
    session_id: NotRequired[Optional[str]]
    
    # Flags for frontend actions
    escalate: NotRequired[bool]
    download_ready: NotRequired[Optional[bool]]
    filename: NotRequired[Optional[str]]
    
