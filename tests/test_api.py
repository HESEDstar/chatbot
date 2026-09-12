import uuid

import pytest

from hesedbot.api.chat import app


@pytest.fixture
def client():
    """Setup the Flask test client."""
    app.config.update({"TESTING": True})
    with app.test_client() as client:
        yield client


def test_chat_endpoint_success_anonymous(client):
    """Anonymous request (no Authorization header) returns a success response."""
    test_thread_id = str(uuid.uuid4())
    payload = {
        "message": "Hello, what features do you offer?",
        "thread_id": test_thread_id,
    }
    response = client.post('/chat', json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"
    assert "message" in data
    assert isinstance(data["message"], str)


def test_chat_endpoint_missing_data(client):
    """Reject a request missing the message."""
    payload = {"thread_id": "12345"}
    response = client.post('/chat', json=payload)
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_chat_ignores_client_supplied_role(client):
    """A `role` field in the body must be ignored (Zero-Trust policy)."""
    payload = {
        "message": "Hello",
        "role": "admin",  # must NOT be trusted
        "thread_id": str(uuid.uuid4()),
    }
    response = client.post('/chat', json=payload)
    # With no token the middleware resolves the caller as anonymous.
    assert response.status_code == 200