"""The HTTP door: one Flask route per operation.

Arguments come from the path, then the query string, then the JSON body, later
sources winning. The answer is the handler's dict as JSON; an `OpError` is
`{"error", "code"}` with its status. An operation marked `owner` is refused to anyone
not in ADMIN_EMAILS, and when it writes, to any page that is not ours."""

from __future__ import annotations

from flask import Flask, jsonify, request

from backend.api.ops import Context, Op, OpError, coerce


def _context() -> Context:
    from backend.api.dev_routes import _is_owner
    from backend.auth.middleware import current_user

    return Context(user=current_user(), owner=_is_owner())


def _arguments(path_args: dict) -> dict:
    raw: dict = {}
    raw.update(request.args.to_dict())
    if request.method != "GET":
        body = request.get_json(silent=True)
        if isinstance(body, dict):
            raw.update(body)
    raw.update(path_args)
    return raw


def refuse(e: OpError):
    return jsonify({"error": e.message, "code": e.code}), e.status


def _view(op: Op):
    def view(**path_args):
        from backend.api.dev_routes import _cross_site, _forbidden, _from_our_site

        ctx = _context()
        if op.owner and not ctx.owner:
            return _forbidden()
        if op.owner and op.writes and not _from_our_site():
            return _cross_site()
        try:
            args = coerce(op, _arguments(path_args))
            return jsonify(op.handler(ctx, args))
        except OpError as e:
            return refuse(e)

    view.__name__ = op.name
    view.__doc__ = op.summary
    return view


def mount(app: Flask, ops: list[Op]) -> None:
    for op in ops:
        app.add_url_rule(op.flask_rule, op.name, _view(op), methods=[op.method])
