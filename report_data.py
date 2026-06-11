#!/usr/bin/env python3
"""
report_data.py — HubSpot pull + metric computation for the RevOps report.

Exposes build_report_data() -> dict, used by the FastAPI app (app.py) to serve
and refresh the report. Pulls Beam AI Deals via the public CRM API, buckets by
US/Eastern Monday weeks and calendar months, computes the four funnel metrics
(Demos, DCC, QDD, Pilots) split by Business Unit (ACE / SPADE), drops the current
incomplete month, and returns a JSON-ready dict.

Auth: HUBSPOT_TOKEN env var (private-app token with crm.objects.deals.read and
crm.schemas.deals.read).
"""

import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

BASE = "https://api.hubapi.com"
PIPELINE_ID = "676188492"                         # Beam AI Deals
OWNER_TEAMS = ["ACE AEs", "CLUB", "SPADE AEs"]
DEMO_SOURCES = ["Marketing", "SDR (Inbound)", "SDR (Outbound)"]
ET = ZoneInfo("US/Eastern")

LBL_JUNK = "Junk/Wrong ICP"
LBL_CANCELLED = "Cancelled"
LBL_NOSHOW = "No Show"
QDD_LABELS = ["Opportunity Identified", "Customer Live", "Pilot Started",
              "Pilot Completed", "Contract Sent", "On-Hold", "Closed Won",
              "Closed Lost", "Take off Done"]
PILOT_CURRENT_LABELS = ["Customer Live", "Pilot Started", "Pilot Completed",
                        "Contract Sent", "On-Hold", "Closed Won", "Closed Lost",
                        "Take off Done"]
PILOT_EVER_LABELS = ["Pilot Started", "Pilot Completed", "Take off Done"]


def _headers():
    token = os.environ.get("HUBSPOT_TOKEN")
    if not token:
        raise RuntimeError("HUBSPOT_TOKEN environment variable is not set.")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def resolve_stage_ids(headers):
    r = requests.get(f"{BASE}/crm/v3/pipelines/deals", headers=headers, timeout=30)
    r.raise_for_status()
    for pipe in r.json().get("results", []):
        if pipe.get("id") == PIPELINE_ID:
            return {s["label"]: s["id"] for s in pipe.get("stages", [])}
    raise RuntimeError(f"pipeline {PIPELINE_ID} not found.")


def _et_midnight_ms(d):
    return int(datetime(d.year, d.month, d.day, tzinfo=ET).timestamp() * 1000)


def _this_week_monday(today_et):
    return today_et.date() - timedelta(days=today_et.weekday())


def fetch_deals(headers, properties, start_ms, end_ms):
    url = f"{BASE}/crm/v3/objects/deals/search"
    filters = [
        {"propertyName": "pipeline", "operator": "EQ", "value": PIPELINE_ID},
        {"propertyName": "owner_team", "operator": "IN", "values": OWNER_TEAMS},
        {"propertyName": "business_unit", "operator": "HAS_PROPERTY"},
        {"propertyName": "meeting_date___time___sales", "operator": "GTE", "value": str(start_ms)},
        {"propertyName": "meeting_date___time___sales", "operator": "LT", "value": str(end_ms)},
    ]
    deals, after = [], None
    while True:
        body = {"filterGroups": [{"filters": filters}], "properties": properties,
                "limit": 100, "sorts": [{"propertyName": "hs_object_id", "direction": "ASCENDING"}]}
        if after:
            body["after"] = after
        resp = requests.post(url, headers=headers, json=body, timeout=60)
        if resp.status_code == 429:
            time.sleep(2)
            continue
        resp.raise_for_status()
        data = resp.json()
        deals.extend(data.get("results", []))
        after = data.get("paging", {}).get("next", {}).get("after")
        if not after:
            break
    return deals


def _parse_meeting(val):
    if val is None:
        return None
    try:
        return datetime.fromtimestamp(int(val) / 1000, tz=ZoneInfo("UTC")).astimezone(ET)
    except (ValueError, TypeError):
        return datetime.fromisoformat(val.replace("Z", "+00:00")).astimezone(ET)


def build_report_data():
    headers = _headers()
    stages = resolve_stage_ids(headers)

    def ids(labels):
        return {stages[l] for l in labels if l in stages}

    junk, cancelled, noshow = stages.get(LBL_JUNK), stages.get(LBL_CANCELLED), stages.get(LBL_NOSHOW)
    qdd_ids = ids(QDD_LABELS)
    pilot_current_ids = ids(PILOT_CURRENT_LABELS)
    pilot_ever_props = [f"hs_v2_date_entered_{stages[l]}" for l in PILOT_EVER_LABELS if l in stages]

    props = ["dealstage", "business_unit", "demo_source_type",
             "meeting_date___time___sales", "owner_team"] + pilot_ever_props

    today_et = datetime.now(ET)
    year = today_et.year
    start_ms = _et_midnight_ms(datetime(year, 1, 1).date())
    end_ms = _et_midnight_ms(_this_week_monday(today_et))

    deals = fetch_deals(headers, props, start_ms, end_ms)

    def blank():
        return {m: {} for m in ("demos", "demos_nc", "dcc", "qdd", "pilots")}
    agg = {g: {"ACE": blank(), "SPADE": blank()} for g in ("weekly", "monthly")}

    for d in deals:
        p = d.get("properties", {})
        bu_raw = p.get("business_unit")
        if bu_raw not in ("true", "false"):
            continue
        bu = "ACE" if bu_raw == "true" else "SPADE"
        dt = _parse_meeting(p.get("meeting_date___time___sales"))
        if dt is None:
            continue
        wk = (dt.date() - timedelta(days=dt.weekday())).isoformat()
        mo = f"{dt.year}-{dt.month:02d}-01"
        stage, src = p.get("dealstage"), p.get("demo_source_type")
        src_in = src in DEMO_SOURCES
        ever_pilot = any(p.get(pe) for pe in pilot_ever_props)

        hits = []
        if src_in and stage != junk:
            hits.append("demos")
        if src_in and stage not in (junk, cancelled):
            hits.append("demos_nc")
        if src_in and stage not in (junk, cancelled, noshow):
            hits.append("dcc")
        if src_in and stage in qdd_ids:
            hits.append("qdd")
        if src is not None and stage in pilot_current_ids and ever_pilot:
            hits.append("pilots")

        for m in hits:
            for grain, key in (("weekly", wk), ("monthly", mo)):
                agg[grain][bu][m][key] = agg[grain][bu][m].get(key, 0) + 1

    week_keys = sorted({k for bu in ("ACE", "SPADE") for m in agg["weekly"][bu]
                        for k in agg["weekly"][bu][m]})
    week_keys = [w for w in week_keys
                 if datetime.fromisoformat(w).date() >= datetime(year, 1, 1).date()]
    month_keys = sorted({k for bu in ("ACE", "SPADE") for m in agg["monthly"][bu]
                         for k in agg["monthly"][bu][m]})
    current_month_key = f"{today_et.year}-{today_et.month:02d}-01"
    month_keys = [k for k in month_keys if k != current_month_key]

    def fmt_week(k):
        d = datetime.fromisoformat(k).date()
        return f"{d.month}/{d.day}"

    def series(grain, bu, metric, keys):
        b = agg[grain][bu][metric]
        return [b.get(k, 0) for k in keys]

    def pack(grain, keys):
        return {bu: {m: series(grain, bu, m, keys)
                     for m in ("demos", "demos_nc", "dcc", "qdd", "pilots")}
                for bu in ("ACE", "SPADE")}

    return {
        "generated": datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M IST"),
        "weekly": {"labels": [fmt_week(k) for k in week_keys], **pack("weekly", week_keys)},
        "monthly": {"labels": [datetime.fromisoformat(k).strftime("%b") for k in month_keys],
                    **pack("monthly", month_keys)},
    }
