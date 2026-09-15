"""Money-page arithmetic and bounded provider snapshots. No campaign mutations."""

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from . import config

GAMES = {"find-the-bird": "Find the Bird", "find-the-dog": "Find the Dog"}
PROVIDERS = {"meta": ("Meta", "spend"), "google_ads": ("Google Ads", "spend"), "admob": ("AdMob", "revenue")}
_lock = threading.Lock()


def amount(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Invalid monetary value") from None
    if not result.is_finite() or result < 0:
        raise ValueError("Invalid monetary value")
    return result


def filters(start=None, end=None, game="all"):
    today = datetime.now(timezone(timedelta(hours=3))).date()
    try:
        last = date.fromisoformat(end) if end else today - timedelta(days=1)
        first = date.fromisoformat(start) if start else last - timedelta(days=29)
    except ValueError:
        raise ValueError("Use valid dates in YYYY-MM-DD format.") from None
    if game not in {"all", *GAMES}:
        raise ValueError("Choose Find the Bird, Find the Dog, or both games.")
    if first > last or last > today or (last - first).days > 365:
        raise ValueError("Choose an ordered date range of up to 366 days, ending today or earlier.")
    return first.isoformat(), last.isoformat(), game


def summarize(reports, game):
    rows, revenues, issues = [], [], []
    spend_ok = revenue_ok = True
    for report in reports:
        valid = (report["status"] == "ok" and report.get("currency") == "TRY"
                 and report.get("timezone") == "Europe/Istanbul")
        if not valid:
            issues.append(report.get("error") or f'{report["provider"]}: incomplete data or incompatible currency/time zone.')
            if report["kind"] == "spend":
                spend_ok = False
            else:
                revenue_ok = False
            continue
        for source in report["rows"]:
            if source["game"] not in GAMES or (game != "all" and source["game"] != game):
                continue
            if report["kind"] == "revenue":
                revenues.append(amount(source["revenue"]))
            else:
                spend = amount(source["spend"])
                revenue = amount(source["revenue"]) if source.get("revenue") is not None else None
                rows.append({**source, "provider": report["provider"], "spend": spend, "revenue": revenue,
                             "ratio": revenue / spend if revenue is not None and spend else None})
    # Reports are required even when a provider has zero delivery.
    names = {r["provider"] for r in reports}
    spend_ok &= {"Meta", "Google Ads"} <= names
    revenue_ok &= "AdMob" in names
    reported_spend = sum((r["spend"] for r in rows), Decimal(0))
    spend = reported_spend if spend_ok else None
    revenue = sum(revenues, Decimal(0)) if revenue_ok else None
    paid = [r for r in rows if r["spend"] > 0]
    measured = [r for r in paid if r["ratio"] is not None]
    best = max(measured, key=lambda r: (r["ratio"], r["spend"], r["ad_id"])) if measured and len(measured) == len(paid) and spend_ok else None
    return {"spend": spend, "reported_spend": reported_spend, "revenue": revenue,
            "ratio": revenue / spend if revenue is not None and spend else None,
            "best": best, "best_ratio": best["ratio"] if best else None,
            "best_projected_revenue": spend * best["ratio"] if best else None,
            "attributed_spend": sum((r["spend"] for r in measured), Decimal(0)),
            "ads": sorted(rows, key=lambda r: (-r["spend"], r["ad_id"])), "issues": issues}


def load_reports(start, end):
    from .money_providers import fetch_report

    settings = config.load_config().get("money", {})
    # The identity/settings digest prevents reuse after account configuration changes.
    key = hashlib.sha256(json.dumps(["money-v1", start, end, settings], sort_keys=True).encode()).hexdigest()
    path = config.data_dir() / "money" / f"{key}.json"
    def read_cache():
        try:
            cached = json.loads(path.read_text())
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(cached["observed_at"])).total_seconds()
            if 0 <= age < 900:
                return cached["reports"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    cached = read_cache()
    if cached is not None:
        return cached
    # Serialize cache misses to cap provider load; cache hits never wait for I/O.
    with _lock:
        cached = read_cache()
        if cached is not None:
            return cached

        def fetch(provider):
            name, kind = PROVIDERS[provider]
            base = {"provider": name, "kind": kind, "rows": [], "start": start, "end": end}
            if not settings.get(provider):
                return {**base, "status": "not_configured", "error": f"{name} reporting is not connected."}
            try:
                result = fetch_report(provider, settings[provider], start, end)
                return {**base, **result, "status": "ok", "observed_at": datetime.now(timezone.utc).isoformat()}
            except Exception:
                # Provider exceptions can embed auth headers, URLs, or response bodies.
                return {**base, "status": "unavailable", "error": f"{name} report unavailable. Check reporting access and retry after the 15-minute cache expires."}

        with ThreadPoolExecutor(max_workers=len(PROVIDERS)) as pool:
            reports = list(pool.map(fetch, PROVIDERS))
        config.atomic_write_json(path, {"observed_at": datetime.now(timezone.utc).isoformat(), "reports": reports})
        return reports
