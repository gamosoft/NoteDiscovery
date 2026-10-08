"""
MCP over Streamable HTTP, served by the backend at /mcp.

Stateless and JSON-only: each POST carries one JSON-RPC message and gets a
JSON reply (or 202 for notifications). We never push server-initiated
messages, so there is no SSE stream and GET/DELETE answer 405.

Tools run through the same MCPServer as the stdio transport. Its client calls
back into this app over loopback using the configured API key, so tool calls
pass through the regular REST endpoints and their auth.
"""

import json
import os
from typing import Callable, List

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from mcp_server.config import MCPConfig
from mcp_server.server import MCPServer, SUPPORTED_PROTOCOL_VERSIONS

# Tool calls hit the local process, where retrying won't help
_LOOPBACK_TIMEOUT = 30.0
_LOOPBACK_ATTEMPTS = 1


def _jsonrpc_error(status_code: int, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"jsonrpc": "2.0", "id": None, "error": {"code": code, "message": message}},
    )


def _loopback_url(request: Request) -> str:
    """URL this process can reach itself on, for the tool client."""
    override = os.getenv("MCP_LOOPBACK_URL", "").strip()
    if override:
        return override.rstrip("/")
    # scope["server"] is the socket uvicorn is actually bound to, so this
    # follows --port/$PORT rather than config.yaml
    server = request.scope.get("server")
    port = server[1] if server and server[1] else 8000
    return f"http://127.0.0.1:{port}"


def build_mcp_router(
    get_api_key: Callable[[], str],
    require_auth: Callable,
    allowed_origins: List[str],
) -> APIRouter:
    """
    Build the /mcp router.

    Args:
        get_api_key: Returns the configured API key ('' when unset)
        require_auth: The app's auth dependency
        allowed_origins: server.allowed_origins; "*" disables the Origin check
    """
    router = APIRouter(dependencies=[Depends(require_auth)], include_in_schema=False)
    check_origin = "*" not in allowed_origins

    @router.post("/mcp")
    def mcp_post(request: Request, body: bytes = Depends(_read_body)) -> Response:
        # DNS-rebinding protection, required by the Streamable HTTP spec
        origin = request.headers.get("origin")
        if check_origin and origin and origin not in allowed_origins:
            return _jsonrpc_error(403, -32600, "Origin not allowed")

        version = request.headers.get("mcp-protocol-version")
        if version and version not in SUPPORTED_PROTOCOL_VERSIONS:
            return _jsonrpc_error(400, -32600, f"Unsupported MCP protocol version: {version}")

        try:
            message = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return _jsonrpc_error(400, -32700, f"Parse error: {e}")

        # Batching was removed from the protocol in 2025-06-18
        if not isinstance(message, dict):
            return _jsonrpc_error(400, -32600, "Invalid Request: expected a single JSON-RPC message")

        config = MCPConfig(
            base_url=_loopback_url(request),
            api_key=get_api_key() or None,
            timeout=_LOOPBACK_TIMEOUT,
            max_retries=_LOOPBACK_ATTEMPTS,
        )
        reply = MCPServer(config, require_initialize=False).handle_message(message)

        if reply is None:
            return Response(status_code=202)
        return JSONResponse(content=reply)

    @router.api_route("/mcp", methods=["GET", "DELETE"])
    def mcp_not_allowed() -> Response:
        return Response(status_code=405, headers={"Allow": "POST"})

    return router


async def _read_body(request: Request) -> bytes:
    # Read in a dependency so the sync endpoint above can run in the threadpool
    # (its loopback calls block) without touching the async request stream
    return await request.body()
