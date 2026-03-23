from flask import Flask, request, jsonify
from hesedbot.api.downloads import downloads_bp
from hesedbot.core.state import AgentState
from hesedbot.core.graph import app_graph
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig
import os
from hesedbot.config import Config

def create_app():
    app = Flask(__name__)
    app.config['UPLOAD_FOLDER'] = Config.UPLOAD_FOLDER

    @app.route('/health', methods=['GET'])
    def health_check():
        return jsonify({"status": "ok"}), 200

    return app

app = create_app()
# Register blueprints
app.register_blueprint(downloads_bp, url_prefix='/downloads')


@app.route('/chat', methods=['POST'])
def chat():
    """Endpoint to handle chat messages from the frontend."""
    data = request.json
    user_message = data.get('message')
    user_role = data.get('role', 'anonymous')  # Default to 'anonymous' if not provided
    thread_id = data.get('thread_id')  # for multi-turn conversations

    if not thread_id and not user_message:
        return jsonify({"error": "thread_id and message are required"}), 400
    
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    # Check if the graph is currently frozen
    state = app_graph.get_state(config)
    is_interrupted = any(task.interrupts for task in state.tasks)
    
    if is_interrupted:
        app_graph.update_state(config, {"messages": [HumanMessage(content=user_message)]})
    # Update the state with the new user message
    input_data: AgentState = {"messages": [HumanMessage(content=user_message)], "user_role": user_role}
    try:
        # We use invoke() for a standard synchronous REST response. 
        final_state = app_graph.invoke(input_data, config)
        
        # Fetch the latest message to return to the frontend
        last_message = final_state["messages"][-1].content
        
        return jsonify({
            "status": "success",
            "escalated": is_now_interrupted,
            "message": last_message
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500