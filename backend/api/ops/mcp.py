"""The MCP door: every operation as a tool, over JSON-RPC at POST /mcp.

The Model Context Protocol's streamable-HTTP transport, the request/response half:
`initialize`, `tools/list`, `tools/call` and `ping`. No server-to-client stream, so
GET /mcp is 405 — nothing here needs to push. An assistant that speaks MCP sees the
same operations the website uses, with the same parameters, because both are read
off the registry.

Who may call: a session cookie, as on every other route, or `Authorization: Bearer`
with the value of MCP_TOKEN, which stands for the owner (it is the owner's token to
hand to their own assistant). With MCP_TOKEN unset the bearer door is shut; the
cookie door still works."""

from __future__ import annotations

import json
import os

from flask import Flask, Response, g, jsonify, request

from backend.api.ops import REGISTRY, Context, Op, OpError, coerce

PROTOCOL = "2025-06-18"
SERVER = {"name": "fashion-archive", "version": "1"}
_JSON = "application/json"


def tool(op: Op) -> dict:
    props, required = {}, []
    for p in op.params:
        schema: dict = {"type": p.type}
        if p.doc:
            schema["description"] = p.doc
        if p.choices:
            schema["enum"] = list(p.choices)
        if p.default is not None:
            schema["default"] = p.default
        props[p.name] = schema
        if p.required:
            required.append(p.name)
    lines = [op.summary]
    if op.detail:
        lines += ["", op.detail]
    if op.reads:
        lines += ["", "Reads: " + ", ".join(op.reads) + "."]
    if op.owner:
        lines += ["", "Owner only."]
    return {
        "name": op.name,
        "title": op.name.replace("_", " "),
        "description": "\n".join(lines),
        "inputSchema": {"type": "object", "properties": props, "required": required},
        "annotations": {
            "readOnlyHint": not op.writes,
            "destructiveHint": op.writes and op.method == "DELETE",
            "idempotentHint": op.method in ("GET", "PUT", "DELETE"),
            "openWorldHint": False,
        },
    }


def tools() -> list[dict]:
    return [tool(o) for o in REGISTRY.all()]


def _caller() -> Context | None:
    """The session's user, or the owner by bearer token, or nobody."""
    want = os.environ.get("MCP_TOKEN", "").strip()
    sent = request.headers.get("Authorization", "")
    if want and sent.startswith("Bearer ") and sent[7:].strip() == want:
        return Context(user=None, owner=True)
    from backend.auth import db
    from backend.auth import repository as repo
    from backend.auth.middleware import SESSION_COOKIE_NAME

    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    with db.transaction() as conn:
        user = repo.get_session_user(conn, token)
    if user is None:
        return None
    g.current_user = user  # so the owner check reads the same user every route does
    from backend.api.dev_routes import _is_owner

    return Context(user=user, owner=_is_owner())


def _error(id_, code: int, message: str, status: int = 200):
    return jsonify(
        {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}
    ), status


def _result(id_, result):
    return jsonify({"jsonrpc": "2.0", "id": id_, "result": result})


def call(ctx: Context, name: str, arguments: dict) -> dict:
    """One tool call, answered in MCP's content shape."""
    op = REGISTRY.get(name)
    if op is None:
        raise OpError(f"no tool named {name}", "NOT_FOUND", 404)
    if op.owner and not ctx.owner:
        raise OpError("not an owner of this archive", "NOT_OWNER", 403)
    try:
        answer = op.handler(ctx, coerce(op, arguments or {}))
    except OpError as e:
        return {
            "content": [{"type": "text", "text": f"{e.code}: {e.message}"}],
            "isError": True,
        }
    return {
        "content": [{"type": "text", "text": json.dumps(answer, ensure_ascii=False)}],
        "structuredContent": answer if isinstance(answer, dict) else {"result": answer},
    }


def endpoint():
    if request.method == "GET":
        return Response("no stream here: POST JSON-RPC", status=405, mimetype="text/plain")
    ctx = _caller()
    if ctx is None:
        return _error(None, -32001, "authentication required", 401)
    msg = request.get_json(silent=True)
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _error(None, -32600, "not a JSON-RPC 2.0 request", 400)
    method, id_, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if method == "notifications/initialized" or (
        id_ is None and str(method).startswith("notifications/")
    ):
        return Response(status=202)
    if method == "initialize":
        return _result(
            id_,
            {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}}, "serverInfo": SERVER},
        )
    if method == "ping":
        return _result(id_, {})
    if method == "tools/list":
        return _result(id_, {"tools": tools()})
    if method == "tools/call":
        try:
            return _result(
                id_, call(ctx, str(params.get("name", "")), params.get("arguments") or {})
            )
        except OpError as e:
            return _error(id_, -32602 if e.status == 400 else -32000, e.message)
    return _error(id_, -32601, f"method not found: {method}")


PUBLIC_MCP_ENDPOINTS = {"mcp"}


def mount(app: Flask) -> None:
    app.add_url_rule("/mcp", "mcp", endpoint, methods=["GET", "POST"])
