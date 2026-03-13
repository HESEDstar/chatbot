from langchain.tools import tool, ToolRuntime
from langgraph.types import Command
from langchain_core.messages import ToolMessage
from langchain.messages import RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from pydantic import BaseModel, Field
from hesedbot.services.pdf_engine import generate_filename # Wraps your existing utils.py

class LessonNoteInput(BaseModel):
    subject: str = Field(description="The subject matter (e.g.,'English Language')")
    school_class: str = Field(description="The target grade level (e.g., 'JSS 3')")
    topic: str = Field(description="The specific topic to cover")
    duration: str = Field(description="Duration of the lesson")
    week: int = Field(description="Academic week number")
    term: str = Field(description="Academic term")

# Schema to capture lead information for the generate_lead tool
class LeadInput(BaseModel):
    name: str = Field(description="The full name of the lead. required.")
    role: str = Field(description="The role of the lead (e.g., 'teacher', 'principal'). required.")
    email: str = Field(description="The email address of the lead. required.")
    school_name: str = Field(description="The name of the school associated with the lead. required.")

@tool(args_schema=LessonNoteInput)
async def generate_lesson_note(
    subject: str, school_class: str, topic: str, duration: str, week: int, term: str, 
    runtime: ToolRuntime
    ) -> str:
    """
    Generates a lesson note PDF based on the provided parameters. Returns the filename of the generated file.
    Args:
        subject (str): The subject matter (e.g.,'English Language')
        school_class (str): The target grade level (e.g., 'JSS 3')
        topic (str): The specific topic to cover
        duration (str): Duration of the lesson
        week (int): Academic week number
        term (str): Academic term
    Returns:
        str: The filename of the generated lesson note PDF.
    """
    try:
        filename = generate_filename(subject, school_class, topic, duration, week, term)
        # Return the filename
        return f"__FILE_GENERATED__:{filename}"
    except Exception as e:
        # return the error the the Agent can read it
        return f"TOOL_ERROR: The system could not generate the PDF. Technical details: {str(e)}"

# The Human-in-the-loop Logic: The code below only sets the flag to True.
@tool
def escalate_issue(reason: str, runtime: ToolRuntime) -> Command:
    """
    Flag the current session for escalation to a human agent.
    Args:
        reason (str): The reason for escalation, provided by the agent.
    Returns:
        Command: A command that updates the state to indicate escalation.
    """
    
    return Command(
        update={
            "escalate": True,
            "messages": [
                ToolMessage(
                    content=f"Escalation triggered successfully. Reason: {reason}. Pausing AI...",
                    tool_name="escalate_issue",
                    tool_call_id=runtime.tool_call_id
                )
            ]
        }
    )



@tool(args_schema=LeadInput)
def generate_lead(name: str, role: str, email: str, school_name: str, runtime: ToolRuntime) -> Command:
    """
    Upload lead information to the database.
    """
    # This is a placeholder implementation. In a real application, this function would interact with a database or an external CRM system to store the lead information.
    # For demonstration purposes, we will just return a success message.

    # Lead generated successfully: Name: {name}, Role: {role}, Email: {email}, School: {school_name}
    return Command(
        update={
            "lead_captured": True,
            "messages": [
                ToolMessage(
                    content="SYSTEM: Lead saved successfully. Proceed to say a final goodbye.",
                    tool_name="generate_lead",
                    tool_call_id=runtime.tool_call_id
                )
            ]
        }
    )    

# Update the conversation history by removing all messages
@tool
def clear_conversation() -> Command:
    """Clear the conversation history."""

    return Command(
        update={
            "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)],
        }
    )