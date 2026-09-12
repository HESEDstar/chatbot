"""Authentication middleware for the HesedBot Flask API.

Implements the Zero-Trust policy: the client is NEVER trusted to supply a role.
The only source of truth for a caller's identity/role is the main Hesed Edusuite
backend, queried directly using the Laravel Sanctum access token forwarded in
the `Authorization: Bearer <token>` header.
"""

import requests
from functools import wraps

from flask import request, g, jsonify

from hesedbot.config import Config


def require_auth_optional(f):
    """Resolve the caller's role without requiring a token.

    - No Authorization header      -> defaults `g.user_role` to "anonymous".
    - Valid Bearer token           -> sets `g.user_role` and `g.user_id` from the
                                      verified Hesed backend response.
    - Expired/invalid token        -> HTTP 401 (request halted).
    - Verification service down    -> HTTP 503 (fail closed for the caller).
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # Defaults for unauthenticated visitors.
        g.user_role = "anonymous"
        g.user_id = None

        auth_header = request.headers.get('Authorization')

        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()
            if not token:
                return jsonify({"status": "error", "error": "Session expired or invalid."}), 401

            try:
                resp = requests.get(
                    Config.HESED_VERIFY_URL,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                    timeout=Config.AUTH_TIMEOUT_SECONDS,
                )
            except requests.RequestException:
                return jsonify({"status": "error", "error": "Authentication service unavailable."}), 503

            if resp.status_code == 200:
                try:
                    data = resp.json()
                except ValueError:
                    return jsonify({"status": "error", "error": "Authentication service unavailable."}), 503

                # Hesed returns the profile nested under "user"; fall back to a
                # flat object to stay resilient against response-shape changes.
                user_data = data.get("user") or {}
                role = user_data.get("role") or data.get("role") or "anonymous"
                g.user_role = str(role)
                g.user_id = user_data.get("id") or data.get("id")
            else:
                return jsonify({"status": "error", "error": "Session expired or invalid."}), 401

        return f(*args, **kwargs)

    return decorated


def require_roles(*allowed_roles):
    """Reject requests whose verified role is not in the allow-list."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if g.user_role not in allowed_roles:
                return jsonify({
                    "status": "error",
                    "error": "You do not have permission to perform this action.",
                }), 403
            return f(*args, **kwargs)
        return wrapped
    return decorator
