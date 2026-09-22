"""What the three services behind the archive are costing, read from their own APIs.

Each read is best-effort and separately reported: a missing key or a slow API turns
into `{"ok": False, "error": ...}` for that provider and nothing else on the page
waits for it. Answers are cached for ten minutes because none of these numbers
move faster than that and every one is a network round trip.

Render has no billing endpoint. What it can say is which plan each service is on,
and the number shown for it is that plan's list price — marked as such, because the
invoice is the invoice and this is arithmetic.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

TIMEOUT = 12
CACHE_SECONDS = 600

# Render list prices in USD per month, by plan slug as the API reports it. Used only
# to label a service; a plan not named here shows its slug and no number.
RENDER_LIST_PRICES = {
    "free": 0.0,
    "starter": 7.0,
    "standard": 25.0,
    "pro": 85.0,
    "pro_plus": 175.0,
    "basic_256mb": 6.0,
    "basic_1gb": 19.0,
    "basic_4gb": 55.0,
}

# R2 storage, USD per GB-month, after the 10 GB free allowance. Operations are not
# estimated: the archive's traffic is a few thousand writes a day, cents at most.
R2_STORAGE_PER_GB = 0.015
R2_FREE_GB = 10.0

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def _cached(name: str, compute):
    with _lock:
        hit = _cache.get(name)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
    try:
        value = compute()
    except Exception as e:  # noqa: BLE001 — one provider down must not take the page
        value = {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}
    with _lock:
        _cache[name] = (time.monotonic(), value)
    return value


def _call(url: str, headers: dict, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} from {url.split('/')[2]}") from e


def anthropic_costs(days: int = 30) -> dict:
    """Per-day spend from the Admin API's cost report, and the month so far."""

    def compute():
        key = os.environ.get("ANTHROPIC_ADMIN_KEY", "").strip()
        if not key:
            return {"ok": False, "error": "ANTHROPIC_ADMIN_KEY not set"}
        start = (date.today() - timedelta(days=days)).isoformat()
        body = _call(
            "https://api.anthropic.com/v1/organizations/cost_report"
            f"?starting_at={start}T00:00:00Z&bucket_width=1d",
            {"x-api-key": key, "anthropic-version": "2023-06-01"},
        )
        rows = []
        for bucket in body.get("data", []):
            usd = 0.0
            for r in bucket.get("results", []):
                try:
                    usd += float(r.get("amount") or 0)
                except (TypeError, ValueError):
                    pass
            rows.append({"date": bucket["starting_at"][:10], "usd": round(usd, 4)})
        month = date.today().strftime("%Y-%m")
        return {
            "ok": True,
            "days": rows,
            "month_usd": round(sum(r["usd"] for r in rows if r["date"].startswith(month)), 2),
            "window_usd": round(sum(r["usd"] for r in rows), 2),
        }

    return _cached("anthropic", compute)


def cloudflare_r2(bucket: str | None = None) -> dict:
    """Bytes and objects in the bucket, by day, and a storage estimate at list price."""

    def compute():
        token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
        account = os.environ.get("R2_ACCOUNT_ID", "").strip()
        if not token or not account:
            return {"ok": False, "error": "CLOUDFLARE_API_TOKEN or R2_ACCOUNT_ID not set"}
        start = (date.today() - timedelta(days=30)).isoformat()
        query = {
            "query": (
                "query($a:String!,$d:Date!){viewer{accounts(filter:{accountTag:$a})"
                "{r2StorageAdaptiveGroups(limit:200,filter:{date_geq:$d},orderBy:[date_DESC])"
                "{dimensions{date bucketName}max{payloadSize objectCount}}}}}"
            ),
            "variables": {"a": account, "d": start},
        }
        body = _call(
            "https://api.cloudflare.com/client/v4/graphql",
            {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            query,
        )
        accounts = ((body.get("data") or {}).get("viewer") or {}).get("accounts") or []
        groups = accounts[0].get("r2StorageAdaptiveGroups", []) if accounts else []
        wanted = bucket or os.environ.get("R2_BUCKET", "").strip()
        days = [
            {
                "date": g["dimensions"]["date"],
                "bytes": g["max"]["payloadSize"],
                "objects": g["max"]["objectCount"],
            }
            for g in groups
            if not wanted or g["dimensions"]["bucketName"] == wanted
        ]
        days.sort(key=lambda d: d["date"])
        latest = days[-1] if days else {"bytes": 0, "objects": 0, "date": None}
        gb = latest["bytes"] / 1e9
        return {
            "ok": True,
            "bucket": wanted or None,
            "bytes": latest["bytes"],
            "objects": latest["objects"],
            "as_of": latest["date"],
            "days": days,
            "storage_usd_month": round(max(0.0, gb - R2_FREE_GB) * R2_STORAGE_PER_GB, 2),
        }

    return _cached("cloudflare", compute)


# Bandwidth is the one line on Render's bill that is not a plan price, and the one
# that once cost $80 in a week. Render meters it per service, hourly, in MB; what
# is shown is this month's total and the overage at Render's published rate above
# the allowance a paid workspace gets. The allowance is stated, not fetched.
RENDER_BANDWIDTH_INCLUDED_GB = 100.0
RENDER_BANDWIDTH_PER_GB = 0.15


def _bandwidth_gb_month(service_id: str, headers: dict) -> float | None:
    start = date.today().replace(day=1).isoformat() + "T00:00:00Z"
    try:
        body = _call(
            f"https://api.render.com/v1/metrics/bandwidth?resource={service_id}&startTime={start}",
            headers,
        )
    except RuntimeError:
        return None
    mb = 0.0
    for series in body if isinstance(body, list) else []:
        for point in series.get("values", []):
            mb += float(point.get("value") or 0)
    return round(mb / 1024, 3)


def render_services(prefix: str = "fashion-archive") -> dict:
    """Each service and database on its plan, priced at list, with the month's
    bandwidth beside it."""

    def compute():
        key = os.environ.get("RENDER_API_KEY", "").strip()
        if not key:
            return {"ok": False, "error": "RENDER_API_KEY not set"}
        headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
        rows = []
        for item in _call("https://api.render.com/v1/services?limit=50", headers):
            s = item["service"]
            if not s["name"].startswith(prefix):
                continue
            plan = (s.get("serviceDetails") or {}).get("plan") or "?"
            rows.append(
                {
                    "name": s["name"],
                    "kind": s.get("type"),
                    "plan": plan,
                    "list_usd_month": RENDER_LIST_PRICES.get(plan),
                    "suspended": s.get("suspended") == "suspended",
                    "bandwidth_gb_month": _bandwidth_gb_month(s["id"], headers),
                }
            )
        for item in _call("https://api.render.com/v1/postgres?limit=20", headers):
            p = item["postgres"]
            if not p["name"].startswith(prefix):
                continue
            plan = p.get("plan") or "?"
            rows.append(
                {
                    "name": p["name"],
                    "kind": "postgres",
                    "plan": plan,
                    "list_usd_month": RENDER_LIST_PRICES.get(plan),
                    "suspended": False,
                }
            )
        priced = [r["list_usd_month"] for r in rows if r["list_usd_month"] is not None]
        gb = sum(r.get("bandwidth_gb_month") or 0 for r in rows)
        return {
            "ok": True,
            "services": rows,
            "list_usd_month": round(sum(priced), 2),
            "bandwidth_gb_month": round(gb, 2),
            "bandwidth_included_gb": RENDER_BANDWIDTH_INCLUDED_GB,
            "bandwidth_overage_usd": round(
                max(0.0, gb - RENDER_BANDWIDTH_INCLUDED_GB) * RENDER_BANDWIDTH_PER_GB, 2
            ),
        }

    return _cached("render", compute)
