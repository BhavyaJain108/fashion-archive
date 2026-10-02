"""One registry, three doors: the HTTP route, the MCP tool and the docs agree."""

import pytest
from flask import Flask

from backend.api.ops import Context, Op, OpError, Param, Registry, coerce
from backend.api.ops import docs as docs_mod
from backend.api.ops import http as http_mod
from backend.api.ops import mcp as mcp_mod

pytestmark = pytest.mark.unit


def _echo(ctx, a):
    if a["n"] == 13:
        raise OpError("unlucky", "UNLUCKY", 418)
    return {"got": a, "owner": ctx.owner}


ECHO = Op(
    name="test_echo",
    family="catalogue",
    summary="Echo the arguments.",
    method="GET",
    path="/api/test/echo/{item}",
    handler=_echo,
    params=(
        Param("item", "string", required=True),
        Param("n", "integer", default=1),
        Param("flag", "boolean", default=False),
        Param("sort", "string", default="type", choices=("type", "latest")),
        Param("tags", "array", default=[]),
    ),
    reads=("nothing",),
)


class TestCoerce:
    def test_types_and_defaults(self):
        got = coerce(ECHO, {"item": "x", "n": "7", "flag": "yes", "tags": "a,b"})
        assert got == {"item": "x", "n": 7, "flag": True, "sort": "type", "tags": ["a", "b"]}

    def test_required_choices_and_bad_values(self):
        with pytest.raises(OpError, match="item is required"):
            coerce(ECHO, {})
        with pytest.raises(OpError, match="sort must be one of"):
            coerce(ECHO, {"item": "x", "sort": "price"})
        with pytest.raises(OpError, match="n must be an integer"):
            coerce(ECHO, {"item": "x", "n": "seven"})

    def test_unknown_keys_are_ignored(self):
        assert "extra" not in coerce(ECHO, {"item": "x", "extra": 1})

    def test_path_names_must_be_declared(self):
        with pytest.raises(ValueError, match="path names"):
            Op(name="bad", family="x", summary="s", method="GET", path="/a/{b}", handler=_echo)

    def test_a_registry_refuses_twins(self):
        r = Registry()
        r.add(ECHO)
        with pytest.raises(ValueError, match="twice"):
            r.add(ECHO)


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setattr(http_mod, "_context", lambda: Context(user=None, owner=False))
    app = Flask(__name__)
    http_mod.mount(app, [ECHO])
    return app


class TestHttp:
    def test_path_query_and_errors(self, app):
        c = app.test_client()
        body = c.get("/api/test/echo/skirt?n=2&flag=1&tags=a,b").get_json()
        assert body["got"] == {
            "item": "skirt",
            "n": 2,
            "flag": True,
            "sort": "type",
            "tags": ["a", "b"],
        }
        r = c.get("/api/test/echo/skirt?sort=price")
        assert r.status_code == 400 and r.get_json()["code"] == "BAD_REQUEST"
        r = c.get("/api/test/echo/skirt?n=13")
        assert r.status_code == 418 and r.get_json() == {"error": "unlucky", "code": "UNLUCKY"}


class TestMcp:
    def test_tool_schema_comes_from_the_params(self):
        t = mcp_mod.tool(ECHO)
        assert t["name"] == "test_echo"
        assert t["inputSchema"]["required"] == ["item"]
        assert t["inputSchema"]["properties"]["sort"]["enum"] == ["type", "latest"]
        assert t["inputSchema"]["properties"]["n"]["default"] == 1
        assert t["annotations"]["readOnlyHint"] is True
        assert "Reads: nothing." in t["description"]

    def test_json_rpc_round_trip(self, monkeypatch):
        from backend.api.ops import REGISTRY

        monkeypatch.setattr(REGISTRY, "_ops", {**REGISTRY._ops, "test_echo": ECHO})
        monkeypatch.setattr(mcp_mod, "_caller", lambda: Context(user=None, owner=True))
        app = Flask(__name__)
        mcp_mod.mount(app)
        c = app.test_client()

        init = c.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        )
        assert init.get_json()["result"]["protocolVersion"] == mcp_mod.PROTOCOL
        assert (
            c.post(
                "/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}
            ).status_code
            == 202
        )

        listed = c.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).get_json()
        assert "test_echo" in {t["name"] for t in listed["result"]["tools"]}

        called = c.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "test_echo", "arguments": {"item": "skirt", "n": 2}},
            },
        ).get_json()
        assert called["result"]["structuredContent"]["got"]["n"] == 2
        assert called["result"]["structuredContent"]["owner"] is True

        failed = c.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "test_echo", "arguments": {"item": "x", "n": 13}},
            },
        ).get_json()
        assert failed["result"]["isError"] is True
        assert "UNLUCKY" in failed["result"]["content"][0]["text"]

        missing = c.post("/mcp", json={"jsonrpc": "2.0", "id": 5, "method": "nope"}).get_json()
        assert missing["error"]["code"] == -32601
        assert c.get("/mcp").status_code == 405

    def test_nobody_is_refused(self, monkeypatch):
        monkeypatch.setattr(mcp_mod, "_caller", lambda: None)
        app = Flask(__name__)
        mcp_mod.mount(app)
        r = app.test_client().post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert r.status_code == 401

    def test_owner_tools_need_an_owner(self, monkeypatch):
        from backend.api.ops import REGISTRY

        guarded = Op(
            name="test_guard",
            family="dev",
            summary="s",
            method="POST",
            path="/api/test/g",
            handler=lambda c, a: {"ok": True},
            owner=True,
            writes=True,
        )
        monkeypatch.setattr(REGISTRY, "_ops", {**REGISTRY._ops, "test_guard": guarded})
        with pytest.raises(OpError, match="not an owner"):
            mcp_mod.call(Context(user=None, owner=False), "test_guard", {})
        assert mcp_mod.call(Context(user=None, owner=True), "test_guard", {})[
            "structuredContent"
        ] == {"ok": True}


class TestDocs:
    def test_every_route_is_listed_and_legacy_points_at_its_replacement(self, monkeypatch):
        from backend.api import archive_routes

        app = Flask(__name__)
        archive_routes.register_archive_routes(app)
        docs_mod.mount(app)
        d = docs_mod.describe(app)
        fam = {f["key"]: f for f in d["families"]}
        ops = {o["name"]: o for o in fam["catalogue"]["operations"]}
        assert ops["catalogue_products"]["params"][0]["choices"] == ["tiles", "records", "counts"]
        assert ops["catalogue_products"]["mcp_tool"] == "catalogue_products"
        legacy = {r["endpoint"]: r for r in fam["archive"]["legacy"]}
        assert legacy["archive_storefront"]["replaced_by"] == "catalogue_products"
        assert legacy["archive_storefront"]["summary"].startswith("One answer for the whole page")
        assert d["totals"]["undocumented"] == 0
        assert fam["system"]["legacy"][0]["path"] == "/api/docs"

    def test_the_route_serves_it(self):
        from backend.api.ops import dev, me  # noqa: F401 — registering their operations

        app = Flask(__name__)
        docs_mod.mount(app)
        body = app.test_client().get("/api/docs").get_json()
        assert body["mcp"]["endpoint"] == "/mcp"
        assert body["totals"]["operations"] >= 13
