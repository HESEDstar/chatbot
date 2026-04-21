from pathlib import Path
from typing import Literal
from langgraph.graph import StateGraph, END
from hesedbot.core.state import AgentState, UserInformation
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, ToolMessage, AIMessage, HumanMessage
from langgraph.graph.message import RemoveMessage
from hesedbot.tools.lesson_tools import generate_lead, escalate_issue, clear_conversation
from langgraph.prebuilt import ToolNode
from hesedbot.config import Config, SALES_REPRESENTATIVE_PROMPT, PERSONAL_ASSISTANT_PROMPT
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, interrupt
import uuid
# from Ipython.display import Image, display

# Setup LLM (DeepSeek via OpenAI client)
llm = ChatOpenAI(model="deepseek-chat", api_key=Config.OPENAI_API_KEY, base_url=Config.DEEPSEEK_API_URL)
# Bind the structured output to the LLM
info_extractor = llm.with_structured_output(UserInformation, method="function_calling")

ALL_TOOLS = [generate_lead, escalate_issue, clear_conversation]
# Create the standard ToolNode
base_tool_node = ToolNode(ALL_TOOLS)
CURRENT_DIR = Path(__file__).resolve().parent
BASE_DIR = CURRENT_DIR.parent
sales_path = BASE_DIR / "services" / "sales_context.txt"
sms_path = BASE_DIR / "services" / "sms_guide.txt"

def get_platform_context(filepath: Path | str) -> str:
    """
    Simulates fetching real-time data from a database or a cache (Redis).
    In production, getting the context from DB for current pricing, features, or active modules is the best approach.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"[Error]: Context file not found at {filepath}")
        return "Platform context file not found."

# Nodes
def extract_info_node(state: AgentState):
    """
    This node extracts structured client information from the conversation history using the LLM.
    The extracted information is then stored in the state for use in other nodes and tools.
    """

    if state.get("user_role", "anonymous") != "anonymous":
        return {} 
    
    messages = state["messages"]
    # Skip if the last message isn't from the user
    if not messages or not isinstance(messages[-1], HumanMessage):
        return {"messages": []}

    # Check current state for existing data
    current_name = state.get("lead_name")
    current_role = state.get("lead_role")
    current_school = state.get("lead_school_name")
    current_email = state.get("lead_email")

    # If we already have everything, do not make an LLM call!
    if all([current_name, current_role, current_school, current_email]):
        return {"messages": []} # No updates needed
    
    try:
        # pass the last two conversation messages to the LLM to extract client info.
        extracted = info_extractor.invoke(messages[-2:])
        
        # Update the state with the extracted lead information
        return {
            "lead_name": extracted.lead_name or current_name,
            "lead_role": extracted.lead_role or current_role,
            "lead_school_name": extracted.lead_school_name or current_school,
            "lead_email": extracted.lead_email or current_email
        }
    except Exception as e:
        # If extraction fails, return the current state without updates.
        print(f"\n[Extraction Warning]: {str(e)}")
        return {"messages": []}

def goodbye_node(state: AgentState):
    """
    Uses the LLM to generate a dynamic, contextual goodbye message 
    after the lead has been successfully captured.
    """
    # Use fallbacks just in case the extraction was imperfect
    lead_name = state.get('lead_name', 'there')
    school = state.get('lead_school_name', 'your school')
    
    # A pool of varied, natural-sounding goodbye templates
    # goodbye_templates = [
    #     f"Thanks {lead_name}! I've sent the demo access to your email. Our team will reach out soon to show you how Hesed can help {school}. Have a great day! 😊",
    #     f"All set, {lead_name}! Your demo is in your inbox. We're excited to connect with {school} soon. Take care! 🚀",
    #     f"Got it! I've emailed the details over, {lead_name}. Someone from our team will be in touch shortly to discuss {school}'s needs. Have a wonderful day!",
    #     f"Awesome, {lead_name}. Check your email for the demo link! We'll follow up soon to give {school} a proper walkthrough. Talk soon! 👋",
    #     f"Perfect! Demo access is on its way to your inbox, {lead_name}. We look forward to speaking with you and the team at {school}. Have a good one!"
    # ]

    # Inject a final, strict system prompt to force a smooth wrap-up
    wrap_up_instruction = SystemMessage(
        content=(
            f"SYSTEM COMMAND: The lead ({lead_name} from {school}) has been successfully captured in the database. "
            f"Write a simple, warm, and highly personalized goodbye message confirming that their demo access has been sent to their email. "
            "CRITICAL: If the user asks additional questions after the lead is generated, answer them briefly and naturally, but gently remind them that the upcoming demo or their dedicated account manager will cover everything in detail. Do NOT ask any more questions. Do NOT pitch any more features. End the conversation naturally."
            )
        )
    # We use 'llm' instead of 'llm_with_tools' here.
    messages = [wrap_up_instruction] + state["messages"][-2:] 
    # Return the message to be added to the state
    return {"messages": [llm.invoke(messages)]}

def summarize_node(state: AgentState):
    """
    This node handles memory. 
    If history > 15 messages, it creates a summary and deletes old messages.
    """
    messages = state["messages"]
    
    # Only summarize if history is long enough
    if len(messages) > 15:

        # Extract only the messages we are about to delete
        messages_to_summarize = messages[:-5]
        
        # Strip all metadata, tool calls, and system messages
        transcript = []
        for m in messages_to_summarize:
            if isinstance(m, HumanMessage):
                transcript.append(f"User: {m.content}")
            elif isinstance(m, AIMessage) and m.content: 
                # Only grab text content. Ignore AIMessages that are just invisible tool calls.
                transcript.append(f"Bot: {m.content}")

        lean_transcript  = "\n".join(transcript)
        # Prompt to summarize
        system_instruction = (
            "You are compressing chat history for an AI assistant's memory. "
            "CRITICAL: Update the current summary with the new transcript, focus on key decisions, user intent, data provided, and resolved issues. Do not use conversational filler."
        )
        # Current summary + messages to maintain continuity
        existing_summary = state.get("summary", "")
        summarize_prompt = PromptTemplate(
            template="{system_instruction}\n\nCURRENT SUMMARY: {existing_summary}\n\nNEW TRANSCRIPT TO MERGE:\n{lean_transcript}\n\nUPDATED SUMMARY:",
            input_variables=["messages", "existing_summary", "system_instruction"]
        )
        chain = summarize_prompt | llm
        response = chain.invoke({
            "messages": lean_transcript,
            "existing_summary": existing_summary,
            "system_instruction": system_instruction
        })
        
        # RemoveMessage instructions for all but the last 5 messages
        delete_messages = [RemoveMessage(id=m.id) for m in messages_to_summarize if m.id]
        
        return {
            "summary": response.content,
            "messages": delete_messages # LangGraph applies these removals to the state
        }
    
    return {"messages": []} # No changes if not summarizing

def escalate_node(state: AgentState):
    """
    Halts graph execution and hands over to a human.
    """

    # Trigger a backend event (e.g., WebSocket broadcast to Agent UI)
    print(f"\n[BACKEND EVENT] -> Notifying Sales/Support Dashboard for Session...")

    # Pause the graph. The execution stops entirely here.
    # The string passed to interrupt() can be read by the frontend to know the graph state.
    # resume_action = interrupt("Chatbot paused. Waiting for human agent resolution.")

    # Execution resumes ONLY when app_graph.invoke(Command(resume="approve")) is called.
    # if resume_action == "approve":
    #     return {
    #         "escalate": False, # Clear the flag so it doesn't loop
    #         "messages": [
    #             SystemMessage(content="A human agent has successfully resolved the user's portal issue. Resume standard assistance.", name="HesedBot"),
    #         ]
    #     }
    return {
        "escalate": False, # Clear the flag so it doesn't loop
        "messages": [
            SystemMessage(content="The complaint has been successfully logged to the support system, someone will contact them soon. Resume standard assistance.", name="HesedBot")
            ]
            }

def chatbot_node(state: AgentState):
    """Decides the next action based on history and system prompt."""
    role = state.get("user_role", "anonymous")  # Default to 'anonymous' if not set
    path = sales_path if role == "anonymous" else sms_path
    platform_context = get_platform_context(path)  # Fetch real-time platform context
    required_data = {
        "Name": state.get('lead_name'), 
        "Role": state.get('lead_role'), 
        "School Name": state.get('lead_school_name'), 
        "Email": state.get('lead_email')
    }

    # Dynamic Prompting/Tooling: We determine the system prompt and accessible tools based on the user's role.
    if role == "anonymous":
        data_fields = [k for k, v in required_data.items() if v]
        system_content = SALES_REPRESENTATIVE_PROMPT.format(platform_context=platform_context, user_information=", ".join(data_fields))
        tools = [generate_lead] # Anonymous users only get the generate_lead tool to connect them to a human sales rep. No AI tools.
        llm_with_tools = llm.bind_tools(tools)
    else:
        system_content = PERSONAL_ASSISTANT_PROMPT.format(user_role=role, platform_context=platform_context)
        tools = [escalate_issue, clear_conversation] # Registered users gets access to all tools except generate_lead since we haved their data already.
        llm_with_tools = llm.bind_tools(tools)

    if state.get("summary"):
        system_content += f"\n\nSummary of conversation so far: {state.get('summary', '')}"
    
    system_message = SystemMessage(content=system_content)
    messages = [system_message] + state["messages"]
    return {"messages": [llm_with_tools.invoke(messages)]}

# Create a wrapper function for the ToolNode to include RBAC guardrails
def tool_node_with_rbac(state: AgentState):
    """
    Acts as a middleware. It checks RBAC rules, and if they pass,
    it hands off the execution to the official LangGraph ToolNode.
    """
    last_message = state["messages"][-1]

    # Ensure it's an AIMessage before looping
    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
         return {"messages": []} # If it's not an AIMessage with tool calls, we do nothing and return empty messages.
    
    result_messages = []
    authorized_calls = []
    for tool_call in last_message.tool_calls:
        # RBAC Check: Generate Lesson Note
        if tool_call["name"] == "generate_lesson_note":
            if state.get("user_role") not in ["admin", "teacher"]:
                # If unauthorized, we append the ToolMessage to the result_messages with a permission denied content. 
                # This way, the user gets feedback on why their tool call failed, and it also prevents the base_tool_node from ever running.
                result_messages.append(
                    ToolMessage(
                    tool_call_id=tool_call["id"],
                    content="PERMISSION_DENIED: User is not authorized, Only Admins/Teachers can do this."
                ))
                continue # Skip adding to authorized_calls
        authorized_calls.append(tool_call)

    # If there are authorized tool calls, execute them using the base ToolNode logic
    if authorized_calls:
        # create a modified AIMessage that only includes the authorized tool calls
        modified_message = AIMessage(
            content=last_message.content,
            tool_calls=authorized_calls,
            id=last_message.id
        )
        # pass this modified message to the base ToolNode logic
        tool_output = base_tool_node.invoke({"messages": [modified_message]})
        if isinstance(tool_output, dict) and "messages" in tool_output:
            result_messages.extend(tool_output.get("messages", []))
            return {"messages": result_messages}
        elif isinstance(tool_output, list):
            return result_messages + tool_output
        elif hasattr(tool_output, "update"):
            return result_messages + [tool_output]
        
    # If all RBAC checks pass, we return the result messages.
    return {"messages": result_messages}

# Routers
def goodbye_router(state: AgentState) -> Literal["goodbye", "summarize"]:
      
    if state.get("lead_captured"):
        return "goodbye"
    return "summarize"

def router(state: AgentState) -> Literal["tools_node", "summarize"]:
    last_message = state["messages"][-1]
    
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools_node"
    return "summarize"

def escalation_router(state: AgentState) -> Literal["escalate_node", "goodbye", "chatbot_node"]:
    if state.get("escalate"):
        return "escalate_node"
    if state.get("lead_captured"):
        return "goodbye"
    return "chatbot_node"

# Build Graph
workflow = StateGraph(AgentState)
workflow.add_node("extract_info", extract_info_node)
workflow.add_node("summarize", summarize_node)
workflow.add_node("chatbot", chatbot_node)
workflow.add_node("tools_node", tool_node_with_rbac)
workflow.add_node("escalate_node", escalate_node)
workflow.add_node("goodbye", goodbye_node)

workflow.set_entry_point("extract_info")
workflow.add_conditional_edges("extract_info", goodbye_router, {"goodbye": "goodbye", "summarize": "summarize"})
workflow.add_edge("summarize", "chatbot")

workflow.add_conditional_edges("chatbot",  router, {"tools_node": "tools_node", "summarize": END})
workflow.add_conditional_edges("tools_node", escalation_router, {"escalate_node": "escalate_node", "goodbye": "goodbye", "chatbot_node": "chatbot"})
workflow.add_edge("escalate_node", "chatbot") # After escalation, we loop back to the chatbot node to continue the conversation with the human agent's input.
workflow.add_edge("goodbye", END)

memory_saver = MemorySaver()
app_graph = workflow.compile(checkpointer=memory_saver)

def run_interactive_chat():
    # Create a unique session ID for this chat
    thread_id = str(uuid.uuid4())
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    
    print(f"--- HesedBot Testing Terminal (Thread: {thread_id})---")
    print("Type 'exit' or 'quit' to stop.")
    
    # flag to manually lock the terminal in Agent Mode
    agent_mode_active = False

    while True:
        # Check if the graph is currently frozen
        state = app_graph.get_state(config)
        is_interrupted = any(task.interrupts for task in state.tasks)
        
        if is_interrupted:
            agent_mode_active = True

        # If the graph is interrupted, lock the terminal into agent mode
        if agent_mode_active:
            # We are in Human Agent Mode
            print("\n[SYSTEM]: Chat is ESCALATED. You are now the Human Agent.")
            print(" - Type a message to reply to the user.")
            print(" - Type 'user: <msg>' to simulate the user replying back.")
            print(" - Type 'approve' to resolve the ticket and resume the bot.")
            # In a real application, this is where the frontend would show a notification to the human agent.
            # For testing, we simulate the human agent addressing the escalation.
            agent_input = input("\nAgent UI: ")

            if agent_input.strip().lower() == "approve":
                print("\n[SYSTEM]: Resuming AI control...")
                app_graph.invoke(Command(resume="approve"), config)
                agent_mode_active = False
            elif agent_input.lower().startswith("user:"):
                # Simulate user replying to the agent directly into the database
                user_msg = agent_input[5:].strip()
                app_graph.update_state(config, {"messages": [HumanMessage(content=user_msg)]})
            else:
                # Inject agent message directly into the state database (Graph remains frozen)
                app_graph.update_state(config, {"messages": [AIMessage(content=agent_input, name="Human_Agent")]})
                print(f"[Sent to User Frontend]: {agent_input}")
            continue

        # Standard User Mode
        user_input = input("\nUser: ")
        if user_input.lower() in ["exit", "quit"]:
            break

        # Update the state with the new user message
        input_data: AgentState = {"messages": [HumanMessage(content=user_input)], "user_role": "anonymous"} # For testing, we set the role value. In production, this would come from auth system.
        
        # Stream the graph execution
        # We use 'stream' so we can see which node is currently working
        for event in app_graph.stream(input_data, config, stream_mode="updates"):
            # If the graph hits the interrupt during this stream, it yields an event with '__interrupt__'
            if "__interrupt__" in event:
                print(f"\n[Graph Halted]: {event['__interrupt__'][0].value}")
                break

            for node, state_update in event.items():
                if "messages" in state_update and state_update["messages"]:
                    last_message = state_update["messages"][-1]
                    if node in ["chatbot", "goodbye"]:
                        # If it's a regular chatbot response without tool calls, we print it as the bot's message.
                        if isinstance(last_message, AIMessage) and not last_message.tool_calls:
                            print(f"\nBot: {last_message.content}")
                        # The bot is initiating a tool call
                        elif hasattr(last_message, 'tool_calls') and last_message.tool_calls:
                            print(f"\n[System]: Bot is calling tool: {last_message.tool_calls[0]['name']}")

if __name__ == "__main__":
    run_interactive_chat()