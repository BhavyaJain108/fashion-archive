"""The machine room's controls as one operation.

Ten legacy routes, one verb each, become `action` on one resource: the deck's
buttons stop needing a route apiece, and an assistant gets one tool with one enum
rather than ten. The work itself lives in dev_routes, published on the app as
`extensions["dev_actions"]` so this module never reaches into its closures."""

from __future__ import annotations

from flask import current_app

from backend.api.ops import Context, OpError, Param, op

ACTIONS = (
    "run", "learn", "sweep", "sweep_seconds", "release", "pause", "resume",
    "reprobe", "analyse", "climb",
)  # fmt: skip


@op(
    name="dev_brand_action",
    family="dev",
    summary="Steer one brand's scraping: run now, learn, sweep, pause, resume, release, reprobe, analyse, climb.",
    method="POST",
    path="/api/dev/brands/{brand}/actions",
    reads=("schedule.json", "fleet.json", "dossiers"),
    writes=True,
    owner=True,
    replaces=(
        "dev_brand_run",
        "dev_brand_learn",
        "dev_brand_sweep",
        "dev_brand_sweep_seconds",
        "dev_brand_release",
        "dev_brand_enable",
        "dev_reprobe",
        "dev_analyse",
        "dev_climb",
    ),  # fmt: skip
    params=(
        Param("brand", "string", "The brand's domain.", required=True),
        Param("action", "string", "What to do.", required=True, choices=ACTIONS),
        Param(
            "full", "boolean", "run: read the whole shop rather than what changed.", default=False
        ),
        Param(
            "retry_searched",
            "boolean",
            "learn: ask again about fields already given up on.",
            default=False,
        ),
        Param("seconds", "integer", "sweep_seconds: how often to sweep stock; 0 turns it off."),
        Param("kind", "string", "analyse: what the model looks at.", default="brand"),
        Param(
            "level", "string", "climb: the rung to try.", default="t1", choices=("t1", "t1p", "t2")
        ),
    ),
    example={"brand": "huelleyrose.com", "action": "run", "full": False},
)
def dev_brand_action(ctx: Context, a: dict) -> dict:
    """run brings the brand's next turn to now (a worker takes it within ten
    seconds; refused while one holds it). learn queues a finder-only run. sweep
    re-reads stock and price from the bulk feed. pause holds after the current run;
    resume puts it back on its cadence. release takes a dead worker's claim off.
    reprobe, analyse and climb are the learning loop's moves, run in the background;
    watch the dossier fill."""
    from backend.api.dev_routes import _DOMAIN

    act = current_app.extensions.get("dev_actions")
    if act is None:
        raise OpError("the machine room is not mounted", "UNAVAILABLE", 503)
    if not _DOMAIN.match(a["brand"]):
        raise OpError("not a domain", "BAD_DOMAIN")
    payload, status = act(a["brand"], a["action"], a)
    if status >= 400:
        raise OpError(payload.get("error", "refused"), payload.get("code", "REFUSED"), status)
    return payload


OPS = [dev_brand_action]
