import pytest
import requests as requests_lib

from flask import Flask, jsonify, g

from hesedbot.api import middleware as auth_middleware


@pytest.fixture
def auth_client():
    app = Flask(__name__)

    @app.route('/probe', methods=['GET'])
    @auth_middleware.require_auth_optional
    def probe():
        return jsonify({"role": g.user_role, "id": g.user_id, "school_id": g.school_id})

    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}

    def json(self):
        return self._json


def test_middleware_anonymous(auth_client):
    """No Authorization header -> role defaults to 'anonymous'."""
    resp = auth_client.get('/probe')
    assert resp.status_code == 200
    assert resp.get_json()["role"] == "anonymous"


def test_middleware_valid_token(monkeypatch, auth_client):
    """Valid token -> role/id extracted from nested 'user' object."""
    monkeypatch.setattr(
        auth_middleware.requests, "get",
        lambda *a, **k: FakeResponse(200, {"user": {"id": 7, "role": "teacher"}}),
    )
    resp = auth_client.get('/probe', headers={"Authorization": "Bearer good-token"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["role"] == "teacher"
    assert data["id"] == 7


def test_middleware_flat_response_shape(monkeypatch, auth_client):
    """Flat response shape fallback is handled."""
    monkeypatch.setattr(
        auth_middleware.requests, "get",
        lambda *a, **k: FakeResponse(200, {"id": 9, "role": "admin"}),
    )
    resp = auth_client.get('/probe', headers={"Authorization": "Bearer good-token"})
    assert resp.status_code == 200
    assert resp.get_json()["role"] == "admin"


def test_middleware_extracts_school_id(monkeypatch, auth_client):
    """Nested 'user' object -> school_id is extracted for the tenant key."""
    monkeypatch.setattr(
        auth_middleware.requests, "get",
        lambda *a, **k: FakeResponse(200, {"user": {"id": 7, "role": "teacher", "school_id": 42}}),
    )
    resp = auth_client.get('/probe', headers={"Authorization": "Bearer good-token"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["role"] == "teacher"
    assert data["school_id"] == 42


def test_middleware_school_id_flat_shape(monkeypatch, auth_client):
    """Flat response shape -> school_id extracted via fallback."""
    monkeypatch.setattr(
        auth_middleware.requests, "get",
        lambda *a, **k: FakeResponse(200, {"id": 9, "role": "admin", "school_id": 3}),
    )
    resp = auth_client.get('/probe', headers={"Authorization": "Bearer good-token"})
    assert resp.status_code == 200
    assert resp.get_json()["school_id"] == 3


def test_middleware_invalid_token(monkeypatch, auth_client):
    """Invalid/expired token -> HTTP 401."""
    monkeypatch.setattr(
        auth_middleware.requests, "get",
        lambda *a, **k: FakeResponse(401, {"error": "unauthenticated"}),
    )
    resp = auth_client.get('/probe', headers={"Authorization": "Bearer bad-token"})
    assert resp.status_code == 401


def test_middleware_service_unavailable(monkeypatch, auth_client):
    """Verification service down -> HTTP 503 (fail closed)."""
    def boom(*a, **k):
        raise requests_lib.RequestException("timeout")

    monkeypatch.setattr(auth_middleware.requests, "get", boom)
    resp = auth_client.get('/probe', headers={"Authorization": "Bearer x"})
    assert resp.status_code == 503
