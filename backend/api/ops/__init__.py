"""One registry of operations, three doors onto it.

An operation is declared once — its name, what it reads, its parameters and the
function that answers — and from that one declaration come the HTTP route
(`ops.http`), the MCP tool an assistant calls (`ops.mcp`) and the documentation the
machine room shows (`ops.docs`). Nothing is written twice, so the three cannot
disagree, and a new operation is one entry here rather than a route, a tool and a
paragraph kept in step by hand.

The rules that keep it small as it grows:

  one operation per thing, extended with parameters, not sibling paths — a new
  filter on the product list is a `Param`, not a route;

  parameters are typed and named once; the HTTP side reads them from the path, the
  query string or the JSON body and the MCP side from the tool's arguments, and both
  coerce through the same `coerce`;

  an operation answers with a plain dict or raises `OpError`; it never touches
  Flask's request, so the same function serves a browser, an assistant and a test.

Everything registered before this module existed is still served and is listed in
the documentation as legacy, each with the operation that replaces it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

TYPES = ("string", "integer", "number", "boolean", "object", "array")
_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off", "")


class OpError(Exception):
    """An answer the caller must hear about: a bad parameter, nothing found, not yet."""

    def __init__(self, message: str, code: str = "BAD_REQUEST", status: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


@dataclass(frozen=True)
class Param:
    name: str
    type: str = "string"
    doc: str = ""
    required: bool = False
    default: Any = None
    choices: tuple[str, ...] = ()

    def __post_init__(self):
        if self.type not in TYPES:
            raise ValueError(f"{self.name}: type must be one of {TYPES}")


@dataclass(frozen=True)
class Context:
    """Who is asking. `user` is the session's user, None for a bearer token; `owner`
    is whether they may touch the machinery."""

    user: Any = None
    owner: bool = False


@dataclass(frozen=True)
class Op:
    name: str
    family: str
    summary: str
    method: str
    path: str
    handler: Callable[[Context, dict], Any]
    params: tuple[Param, ...] = ()
    detail: str = ""
    reads: tuple[str, ...] = ()
    writes: bool = False
    owner: bool = False
    replaces: tuple[str, ...] = ()
    example: Any = None

    def __post_init__(self):
        if self.method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            raise ValueError(f"{self.name}: method {self.method}")
        if not self.path.startswith("/"):
            raise ValueError(f"{self.name}: path must start with /")
        names = [p.name for p in self.params]
        if len(set(names)) != len(names):
            raise ValueError(f"{self.name}: a parameter is declared twice")
        for p in self.path_params:
            if p not in names:
                raise ValueError(f"{self.name}: path names {{{p}}} but no Param declares it")

    @property
    def path_params(self) -> list[str]:
        out, rest = [], self.path
        while "{" in rest:
            _, _, rest = rest.partition("{")
            name, _, rest = rest.partition("}")
            out.append(name)
        return out

    @property
    def flask_rule(self) -> str:
        rule = self.path
        for p in self.path_params:
            rule = rule.replace("{" + p + "}", "<" + p + ">")
        return rule


def _one(p: Param, raw: Any) -> Any:
    if p.type == "string":
        if not isinstance(raw, str):
            raw = str(raw)
        if p.choices and raw not in p.choices:
            raise OpError(f"{p.name} must be one of {', '.join(p.choices)}")
        return raw
    if p.type == "integer":
        if isinstance(raw, bool):
            raise OpError(f"{p.name} must be an integer")
        try:
            return int(raw)
        except (TypeError, ValueError) as e:
            raise OpError(f"{p.name} must be an integer") from e
    if p.type == "number":
        try:
            return float(raw)
        except (TypeError, ValueError) as e:
            raise OpError(f"{p.name} must be a number") from e
    if p.type == "boolean":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, int | float):
            return bool(raw)
        s = str(raw).strip().lower()
        if s in _TRUE:
            return True
        if s in _FALSE:
            return False
        raise OpError(f"{p.name} must be true or false")
    if p.type == "object":
        if not isinstance(raw, Mapping):
            raise OpError(f"{p.name} must be an object")
        return dict(raw)
    if p.type == "array":
        if isinstance(raw, str):
            return [s for s in raw.split(",") if s]
        if not isinstance(raw, list | tuple):
            raise OpError(f"{p.name} must be a list")
        return list(raw)
    raise AssertionError(p.type)


def coerce(op: Op, raw: Mapping[str, Any]) -> dict[str, Any]:
    """The arguments as the handler expects them: typed, defaulted, checked.

    Keys the operation does not declare are ignored rather than refused, so a client
    one version ahead of the server is not broken by a parameter it added."""
    out: dict[str, Any] = {}
    for p in op.params:
        value = raw.get(p.name)
        if value is None or (isinstance(value, str) and value == "" and p.type != "string"):
            if p.required:
                raise OpError(f"{p.name} is required")
            out[p.name] = p.default
            continue
        out[p.name] = _one(p, value)
    return out


class Registry:
    def __init__(self):
        self._ops: dict[str, Op] = {}

    def add(self, op: Op) -> Op:
        if op.name in self._ops:
            raise ValueError(f"operation {op.name} is registered twice")
        for held in self._ops.values():
            if held.method == op.method and held.path == op.path:
                raise ValueError(f"{op.name}: {op.method} {op.path} is already {held.name}")
        self._ops[op.name] = op
        return op

    def get(self, name: str) -> Op | None:
        return self._ops.get(name)

    def all(self) -> list[Op]:
        return list(self._ops.values())

    def family(self, family: str) -> list[Op]:
        return [o for o in self._ops.values() if o.family == family]

    def replaced(self) -> dict[str, str]:
        """Legacy endpoint name → the operation that replaces it."""
        return {old: op.name for op in self._ops.values() for old in op.replaces}


REGISTRY = Registry()


def op(**kw) -> Callable[[Callable], Op]:
    """Declare an operation around the function that answers it."""

    def wrap(fn):
        detail = kw.pop("detail", None)
        if detail is None and fn.__doc__:
            detail = _dedent(fn.__doc__)
        return REGISTRY.add(Op(handler=fn, detail=detail or "", **kw))

    return wrap


def _dedent(doc: str) -> str:
    lines = doc.strip("\n").splitlines()
    body = lines[1:] if len(lines) > 1 else []
    indent = min((len(x) - len(x.lstrip()) for x in body if x.strip()), default=0)
    return "\n".join([lines[0].strip(), *[x[indent:].rstrip() for x in body]]).strip()
