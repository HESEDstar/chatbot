from typing import Literal
from langgraph.graph import StateGraph, END
from hesedbot.core.state import AgentState
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
ALL_TOOLS = [generate_lead, escalate_issue, clear_conversation]
# Create the standard ToolNode
base_tool_node = ToolNode(ALL_TOOLS)
sales_path = "src/hesedbot/services/sales_context.txt"
sms_path = "src/hesedbot/services/sms_guide.txt"

def get_platform_context(filepath: str) -> str:
    """
    Simulates fetching real-time data from a database or a cache (Redis).
    In production, getting the context from DB for current pricing, features, or active modules is the best approach.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "Platform context file not found."

# Nodes
def summarize_node(state: AgentState):
    """
    This node handles memory. 
    If history > 15 messages, it creates a summary and deletes old messages.
    """
    messages = state["messages"]
    
    # Only summarize if history is long enough
    if len(messages) > 15:
        # Prompt to summarize
        summary_prompt = "Summarize the preceding conversation concisely, focusing on key decisions."
        # Current summary + messages to maintain continuity
        existing_summary = state.get("summary", "")
        summarize_prompt = PromptTemplate(
            template="Current Summary: {existing_summary}\n\nNew Messages: {messages}\n\n{summary_prompt}\n\nSummary:",
            input_variables=["messages", "existing_summary", "summary_prompt"]
        )
        chain = summarize_prompt | llm
        response = chain.invoke({
            "messages": messages,
            "existing_summary": existing_summary,
            "summary_prompt": summary_prompt
        })
        
        # RemoveMessage instructions for all but the last 5 messages
        delete_messages = [RemoveMessage(id=m.id) for m in messages[:-5] if m.id]
        
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
    resume_action = interrupt("Chatbot paused. Waiting for human agent resolution.")

    # Execution resumes ONLY when app_graph.invoke(Command(resume="approve")) is called.
    if resume_action == "approve":
        return {
            "escalate": False, # Clear the flag so it doesn't loop
            "messages": [
                AIMessage(content="The human agent has relinquished control. I'm back! How can I further assist you?", name="HesedBot")
            ]
        }

    return {"escalate": True, "messages": []} # Keep it escalated if not approved 

def chatbot_node(state: AgentState):
    """Decides the next action based on history and system prompt."""
    role = state.get("user_role", "anonymous")  # Default to 'anonymous' if not set
    path = sales_path if role == "anonymous" else sms_path
    platform_context = get_platform_context(path)  # Fetch real-time platform context

    # Dynamic Prompting/Tooling: We determine the system prompt and accessible tools based on the user's role.
    if role == "anonymous":
        system_content = SALES_REPRESENTATIVE_PROMPT.format(platform_context=platform_context)
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

# Router
def router(state: AgentState) -> Literal["tools_node", "summarize"]:
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools_node"
    return "summarize"

def escalation_router(state: AgentState) -> Literal["escalate_node", "chatbot_node"]:
    if state.get("escalate"):
        return "escalate_node"
    return "chatbot_node"

# Build Graph
workflow = StateGraph(AgentState)
workflow.add_node("summarize", summarize_node)
workflow.add_node("chatbot", chatbot_node)
workflow.add_node("tools_node", tool_node_with_rbac)
workflow.add_node("escalate_node", escalate_node)

workflow.set_entry_point("summarize")
workflow.add_edge("summarize", "chatbot")

workflow.add_conditional_edges("chatbot",  router, {"tools_node": "tools_node","summarize": END})
workflow.add_conditional_edges("tools_node", escalation_router, {"escalate_node": "escalate_node", "chatbot_node": "chatbot"})
workflow.add_edge("escalate_node", "chatbot") # After escalation, we loop back to the chatbot node to continue the conversation with the human agent's input.

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
        input_data: AgentState = {"messages": [HumanMessage(content=user_input)], "user_role": "student"} # For testing, we set the role value. In production, this would come from auth system.
        
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
                    if node == "chatbot":
                        # Only print if it's an AI response to avoid clutter
                        if isinstance(last_message, AIMessage) and not last_message.tool_calls:
                            print(f"\nBot: {last_message.content}")
                    elif hasattr(last_message, 'tool_calls') and last_message.tool_calls:
                        print(f"\n[System]: Bot is calling tool: {last_message.tool_calls[0]['name']}")

if __name__ == "__main__":
    run_interactive_chat()