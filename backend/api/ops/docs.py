"""The documentation, read off the running application.

Two sources, one page. The registry says what each operation is, reads and takes.
Flask's own route map says what else is served — every route registered before the
registry existed — and those are listed as legacy, each pointing at the operation
that replaces it where one does. Because it is read at request time nothing here
can drift from the code, and a route without a docstring is a visible gap rather
than a silent one.

GET /api/docs answers JSON; the machine room renders it."""

from __future__ import annotations

import inspect
from datetime import datetime, timezone

from flask import Flask, current_app, jsonify

from backend.api.ops import REGISTRY, Op

# What each family is, in the order the page lists them. Keys are the first path
# segment after /api; the shows API is a dozen of them and is folded under one.
FAMILIES: dict[str, dict] = {
    "catalogue": {
        "name": "Catalogue",
        "about": "What the shop shows: every open brand's live products, ordered and filtered. "
        "Read from the Postgres catalogue the scrapers write (products, product_tags, "
        "product_images), the roster in brands.yml, and the fleet's state in the object store.",
    },
    "me": {
        "name": "Me",
        "about": "The signed-in person's own data: favourites and the brands they follow. "
        "Every row is scoped to the session's user id in the query itself.",
    },
    "dev": {
        "name": "Machine room",
        "about": "The owner's view of the scrapers and the controls on them. Reads the schedule "
        "and fleet objects, per-brand dossiers and the providers' own billing APIs.",
        "owner": True,
    },
    "albums": {"name": "Albums", "about": "Named, hand-ordered groups of saved things."},
    "bag": {"name": "Bag", "about": "A bag of products across brands, checked out shop by shop."},
    "share": {"name": "Share", "about": "Public links to an album or a view, revocable."},
    "auth": {"name": "Auth", "about": "Sign-in by Google or Apple; the session cookie."},
    "archive": {
        "name": "Archive (legacy)",
        "about": "The first catalogue API. Every route is served and is replaced by a "
        "Catalogue operation.",
    },
    "favourites": {"name": "Favourites (legacy)", "about": "Replaced by the Me operations."},
    "brands": {"name": "Following (legacy)", "about": "Replaced by the Me operations."},
    "shows": {
        "name": "Shows (legacy)",
        "about": "Runway seasons, designers and looks from firstVIEW, with the show index in "
        "Postgres and pictures in R2. Frozen: served as it is, not extended.",
    },
    "system": {"name": "System", "about": "Health, documentation and the MCP door."},
}
_SHOWS = {
    "seasons", "recents", "cache", "video", "catalog", "designers", "designer", "browse",
    "search", "index", "download-video", "images", "download-images", "client", "image",
}  # fmt: skip
_SYSTEM = {"health", "docs", "mcp"}
_SKIP = {"static"}


def _family_of(rule: str) -> str:
    parts = rule.strip("/").split("/")
    seg = parts[1] if len(parts) > 1 and parts[0] == "api" else parts[0]
    if seg in _SHOWS:
        return "shows"
    if seg in _SYSTEM:
        return "system"
    if seg == "s":
        return "share"
    return seg if seg in FAMILIES else "system"


def _split(doc: str | None) -> tuple[str, str]:
    """A handler's docstring as (summary, detail). A leading 'GET /path —' is the
    route restating itself and is dropped; when the first line is only the route,
    the summary is the paragraph after it."""
    if not doc:
        return "", ""
    text = inspect.cleandoc(doc)
    head, _, tail = text.partition("\n\n")
    head = " ".join(head.split())
    if head.split(" ")[0] in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        for sep in (" — ", " - "):
            if sep in head:
                head = head.split(sep, 1)[1]
                break
        else:
            head = ""
    if not head and tail:
        head, _, tail = tail.partition("\n\n")
        head = " ".join(head.split())
    return head, tail.strip()


def _param(p) -> dict:
    out = {"name": p.name, "type": p.type, "required": p.required}
    if p.doc:
        out["doc"] = p.doc
    if p.default is not None:
        out["default"] = p.default
    if p.choices:
        out["choices"] = list(p.choices)
    return out


def _op_row(op: Op) -> dict:
    return {
        "name": op.name,
        "method": op.method,
        "path": op.path,
        "summary": op.summary,
        "detail": op.detail,
        "params": [_param(p) for p in op.params],
        "reads": list(op.reads),
        "writes": op.writes,
        "owner": op.owner,
        "replaces": list(op.replaces),
        "example": op.example,
        "mcp_tool": op.name,
    }


def describe(app: Flask) -> dict:
    registered = {o.name for o in REGISTRY.all()}
    replaced = REGISTRY.replaced()
    public = set(app.config.get("PUBLIC_ENDPOINTS") or ())
    legacy: dict[str, list[dict]] = {}
    undocumented = 0
    for rule in app.url_map.iter_rules():
        if rule.endpoint in _SKIP or rule.endpoint in registered:
            continue
        methods = sorted((rule.methods or set()) - {"HEAD", "OPTIONS"})
        fn = app.view_functions.get(rule.endpoint)
        summary, detail = _split(getattr(fn, "__doc__", None))
        if not summary:
            undocumented += 1
        row = {
            "method": "/".join(methods),
            "path": rule.rule.replace("<", "{").replace(">", "}"),
            "endpoint": rule.endpoint,
            "summary": summary,
            "detail": detail,
            "public": rule.endpoint in public,
        }
        if rule.endpoint in replaced:
            row["replaced_by"] = replaced[rule.endpoint]
        legacy.setdefault(_family_of(rule.rule), []).append(row)
    for rows in legacy.values():
        rows.sort(key=lambda r: (r["path"], r["method"]))

    families = []
    for key, meta in FAMILIES.items():
        ops = [_op_row(o) for o in REGISTRY.family(key)]
        old = legacy.pop(key, [])
        if not ops and not old:
            continue
        families.append({"key": key, **meta, "operations": ops, "legacy": old})
    for key, old in legacy.items():  # a family nobody described: still listed
        families.append({"key": key, "name": key, "about": "", "operations": [], "legacy": old})

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "families": families,
        "mcp": {
            "endpoint": "/mcp",
            "protocol": "2025-06-18",
            "tools": len(registered),
            "auth": "session cookie, or Authorization: Bearer <MCP_TOKEN> as the owner",
        },
        "totals": {
            "operations": len(registered),
            "legacy": sum(len(f["legacy"]) for f in families),
            "undocumented": undocumented,
        },
    }


def get_docs():
    """GET /api/docs — every operation and every route, read off this process."""
    return jsonify(describe(current_app))


def mount(app: Flask) -> None:
    app.add_url_rule("/api/docs", "docs", get_docs, methods=["GET"])
