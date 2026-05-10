"""Sandbox tool bridge - allows sandbox subprocess to call MCP tools via HTTP.

Security: each sandbox execution gets a one-time random token that expires
after the execution timeout. The sandbox calls call_tool() which hits
the FastAPI endpoint, which validates the token and proxies to tool_manager.

Token carries allowed_tools metadata so the sandbox can only call tools
that the invoking agent has access to.
"""
import logging
import secrets
import time
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# Active sandbox tokens:
# {token: {"created_at": float, "expires_at": float, "allowed_tools": Optional[List[str]]}}
_active_tokens: Dict[str, Dict[str, Any]] = {}

# Token TTL buffer (seconds added to execution timeout)
_TOKEN_BUFFER = 30


def generate_token(
    timeout: int = 60,
    allowed_tools: Optional[List[str]] = None,
) -> str:
    """Generate a sandbox access token that expires after timeout.

    Args:
        timeout: Execution timeout in seconds
        allowed_tools: Tool whitelist. If None, all tools are accessible.
                       If list, only those tools can be called.

    Returns:
        Random token string
    """
    token = secrets.token_urlsafe(32)
    now = time.time()
    _active_tokens[token] = {
        "created_at": now,
        "expires_at": now + timeout + _TOKEN_BUFFER,
        "allowed_tools": allowed_tools,
    }
    # Cleanup expired tokens
    _cleanup_expired()
    return token


def validate_token(token: str) -> bool:
    """Check if a token is valid and not expired."""
    info = _active_tokens.get(token)
    if not info:
        return False
    if time.time() > info["expires_at"]:
        del _active_tokens[token]
        return False
    return True


def get_token_allowed_tools(token: str) -> Optional[List[str]]:
    """Get the allowed_tools list for a token.

    Returns:
        List of allowed tool names, or None if all tools are allowed.
    """
    info = _active_tokens.get(token)
    if not info:
        return []  # Invalid token — deny all
    return info.get("allowed_tools")


def revoke_token(token: str) -> None:
    """Revoke a token after execution completes."""
    _active_tokens.pop(token, None)


def _cleanup_expired() -> None:
    """Remove expired tokens."""
    now = time.time()
    expired = [t for t, info in _active_tokens.items() if now > info["expires_at"]]
    for t in expired:
        del _active_tokens[t]
