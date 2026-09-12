from flask import Flask, request, jsonify, g
from hesedbot.api.downloads import downloads_bp
from hesedbot.api.middleware import require_auth_optional
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
@require_auth_optional
def chat():
    """Endpoint to handle chat messages from the frontend.

    The caller's role comes exclusively from the verified Sanctum token (set by
    `require_auth_optional`); it is never accepted from the request body.
    """
    data = request.get_json(silent=True) or {}
    user_message = data.get('message')
    thread_id = data.get('thread_id')  # for multi-turn conversations

    if not isinstance(user_message, str) or not user_message.strip():
        return jsonify({"error": "thread_id and message are required"}), 400
    if not isinstance(thread_id, str) or not thread_id.strip():
        return jsonify({"error": "thread_id and message are required"}), 400

    # Input hardening: cap payload sizes to protect the LLM/state store.
    if len(user_message) > 4000:
        return jsonify({"error": "message exceeds the 4000 character limit"}), 400
    if len(thread_id) > 128:
        return jsonify({"error": "thread_id exceeds the 128 character limit"}), 400

    user_message = user_message.strip()
    thread_id = thread_id.strip()

    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    
    # Update the state with the new user message and the verified role.
    input_data: AgentState = {"messages": [HumanMessage(content=user_message)], "user_role": g.user_role}
    try:
        # Use invoke() for a standard synchronous REST response. 
        final_state = app_graph.invoke(input_data, config)

        if not isinstance(final_state, dict):
            final_state = {}
        
        messages = final_state.get("messages", []) 
        if not messages:
            # Log a warning if the graph execution completed but did not return any messages
            print("Warning: Graph execution completed but returned no messages.")
            return jsonify({"error": "The assistant did not return a response."}), 500
        
        # Fetch the latest message to return to the frontend
        if hasattr(messages[-1], 'content'):
            last_message = messages[-1].content
        else:
            print("Warning: The last message does not have a 'content' attribute.")
            last_message = str(messages[-1])  # Fallback to string representation

        if not last_message:
            print("Warning: The assistant returned an empty message content.")
            return jsonify({"error": "The assistant returned an empty response."}), 500

        return jsonify({
            "status": "success",
            "message": last_message
        })
        
    except Exception as e:
        # Log the error on the server side here
        print(f"Error during graph execution: {e}")
        return jsonify({"error": "An internal error occurred while processing your request."}), 500
    
if __name__ == '__main__':
    # Never enable the Flask debugger in production.
    debug = Config.FLASK_ENV != 'production'
    app.run(debug=debug, port=5000, host='0.0.0.0')
    