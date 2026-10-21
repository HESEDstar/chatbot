import uuid

import pytest

from langchain_core.messages import AIMessage

from hesedbot.api import chat as chat_module
from hesedbot.api import middleware as auth_middleware
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


class FakeGraph:
    """Stub for the compiled LangGraph so we can inspect the invoked config."""

    def __init__(self):
        self.last_config = None

    def invoke(self, input_data, config):
        self.last_config = config
        return {"messages": [AIMessage(content="hello")]}


class FakeAuthResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}

    def json(self):
        return self._json


def test_chat_uses_composite_thread_id_for_authenticated(monkeypatch, client):
    """Authenticated callers get a deterministic multi-tenant thread ID."""
    fake_graph = FakeGraph()
    monkeypatch.setattr(chat_module, "app_graph", fake_graph)
    monkeypatch.setattr(
        auth_middleware.requests, "get",
        lambda *a, **k: FakeAuthResponse(
            200, {"user": {"id": 7, "role": "teacher", "school_id": 42}}
        ),
    )

    payload = {"message": "Hello", "thread_id": "client-supplied-uuid"}
    response = client.post(
        '/chat', json=payload, headers={"Authorization": "Bearer good-token"}
    )

    assert response.status_code == 200
    # The frontend UUID must be ignored; the composite key wins.
    assert fake_graph.last_config["configurable"]["thread_id"] == "hesedbot:42:teacher:7"