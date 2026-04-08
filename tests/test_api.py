import pytest
import uuid
# Import the app creation function from your main Flask file
from hesedbot.api.chat import app 

@pytest.fixture
def client():
    """Setup the Flask test client"""
    app.config.update({
        "TESTING": True,
    })
    
    with app.test_client() as client:
        yield client

def test_chat_endpoint_success(client):
    """Test if API returns a valid response for a normal chat message."""
    test_thread_id = str(uuid.uuid4())
    payload = {
        "message": "Hello, what features do you offer?",
        "role": "anonymous",
        "thread_id": test_thread_id
    }
    
    # simulate POST request to endpoint
    response = client.post('/chat', json=payload)
    
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"
    assert "message" in data
    assert isinstance(data["message"], str)

def test_chat_endpoint_missing_data(client):
    """Test if API correctly rejects a request missing the message."""
    payload = {
        "role": "anonymous",
        "thread_id": "12345"
        # "message" is intentionally missing
    }
    
    response = client.post('/chat', json=payload)
    
    assert response.status_code == 400
    assert "error" in response.get_json()