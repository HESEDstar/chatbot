import requests
import uuid
import sys

# Replace with the URL where the Flask app is running
API_URL = "http://127.0.0.1:5000/chat"

def run_api_client():
    # Create a unique session ID for this chat
    thread_id = str(uuid.uuid4())
    user_role = "anonymous"  # Change to "teacher", "admin", etc., for testing RBAC
    
    print(f"--- HesedBot API Testing Terminal ---")
    print(f"Thread ID: {thread_id}")
    print(f"User Role: {user_role}")
    print("Type 'exit' or 'quit' to stop.\n")
    
    while True:
        try:
            # Get user input
            user_input = input("User: ")
            
            if user_input.lower() in ["exit", "quit"]:
                print("Exiting chat. Goodbye!")
                break
            
            if not user_input.strip():
                continue

            # Construct the JSON payload for the Flask API
            payload = {
                "message": user_input,
                "role": user_role,
                "thread_id": thread_id
            }
            
            # Send the request to the Flask server
            response = requests.post(API_URL, json=payload, timeout=60)
            
            # Handle the response
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    print(f"\nBot: {data.get('message')}\n")
                else:
                    print(f"\n[API Error]: {data.get('error', 'Unknown error occurred')}\n")
            else:
                print(f"\n[HTTP Error]: Server returned status code {response.status_code}")
                try:
                    print(f"Details: {response.json()}")
                except ValueError:
                    print(f"Details: {response.text}")
                print()
                
        except requests.exceptions.ConnectionError:
            print("\n[Connection Error]: Could not connect to the API.")
            print(f"Make sure your Flask server is running on {API_URL}\n")
            sys.exit(1)
        except requests.exceptions.Timeout:
            print("\n[Timeout Error]: The server took too long to respond.\n")
        except KeyboardInterrupt:
            print("\nExiting chat. Goodbye!")
            break

if __name__ == "__main__":
    run_api_client()