#!/usr/bin/env python3
"""
RevOps conversion report generator.

Pulls Beam AI Deals from HubSpot via the public CRM API, buckets them by
US/Eastern Monday weeks and calendar months, computes the four funnel metrics
(Demos, DCC, QDD, Pilots) split by Business Unit (ACE / SPADE), and writes a
self-contained interactive HTML report to ./site/index.html.

This mirrors, in plain Python, the exact logic validated in the chat preview:
  - week/month bucketing in US/Eastern (matches HubSpot's account timezone)
  - Pilots uses the TRUE three-stage "has ever been" OR (not the single proxy)
  - two demo denominators: incl. Cancelled and excl. Cancelled
  - Overall = ACE + SPADE (blank Business Unit excluded)

Auth: set HUBSPOT_TOKEN in the environment (a private-app token with
crm.objects.deals.read and crm.schemas.deals.read).
"""

import os
import sys
import json
import time
import base64
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TOKEN = os.environ.get("HUBSPOT_TOKEN")
if not TOKEN:
    sys.exit("ERROR: HUBSPOT_TOKEN environment variable is not set.")

BASE = "https://api.hubapi.com"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

PIPELINE_ID = "676188492"                       # Beam AI Deals
OWNER_TEAMS = ["ACE AEs", "CLUB", "SPADE AEs"]   # base scope (maintained via workflow)
DEMO_SOURCES = ["Marketing", "SDR (Inbound)", "SDR (Outbound)"]
ET = ZoneInfo("US/Eastern")
YEAR = datetime.now(ET).year

# Stage labels used to build the metric sets (resolved to IDs at runtime)
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


# ---------------------------------------------------------------------------
# HubSpot helpers
# ---------------------------------------------------------------------------
def resolve_stage_ids():
    """Map stage label -> internal id for the Beam AI Deals pipeline."""
    r = requests.get(f"{BASE}/crm/v3/pipelines/deals", headers=HEADERS, timeout=30)
    r.raise_for_status()
    for pipe in r.json().get("results", []):
        if pipe.get("id") == PIPELINE_ID:
            return {s["label"]: s["id"] for s in pipe.get("stages", [])}
    sys.exit(f"ERROR: pipeline {PIPELINE_ID} not found.")


def et_midnight_epoch_ms(d):
    """Epoch millis for US/Eastern midnight of date d (date object)."""
    dt = datetime(d.year, d.month, d.day, tzinfo=ET)
    return int(dt.timestamp() * 1000)


def this_week_monday(today_et):
    return today_et.date() - timedelta(days=today_et.weekday())


def fetch_deals(properties, start_ms, end_ms):
    """Page through all in-scope deals with the requested properties."""
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
        body = {"filterGroups": [{"filters": filters}],
                "properties": properties, "limit": 100,
                "sorts": [{"propertyName": "hs_object_id", "direction": "ASCENDING"}]}
        if after:
            body["after"] = after
        resp = requests.post(url, headers=HEADERS, json=body, timeout=60)
        if resp.status_code == 429:               # rate limit: back off and retry
            time.sleep(2)
            continue
        resp.raise_for_status()
        data = resp.json()
        deals.extend(data.get("results", []))
        after = data.get("paging", {}).get("next", {}).get("after")
        if not after:
            break
    if len(deals) >= 10000:
        print("WARNING: hit 10k search ceiling; window may need date-chunking.")
    return deals


def parse_meeting(val):
    """meeting_date prop may arrive as epoch-ms string or ISO 8601."""
    if val is None:
        return None
    try:
        return datetime.fromtimestamp(int(val) / 1000, tz=ZoneInfo("UTC")).astimezone(ET)
    except (ValueError, TypeError):
        return datetime.fromisoformat(val.replace("Z", "+00:00")).astimezone(ET)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    stages = resolve_stage_ids()

    def ids(labels):
        out = []
        for l in labels:
            if l in stages:
                out.append(stages[l])
            else:
                print(f"WARNING: stage label not found: {l!r}")
        return set(out)

    junk = stages.get(LBL_JUNK)
    cancelled = stages.get(LBL_CANCELLED)
    noshow = stages.get(LBL_NOSHOW)
    qdd_ids = ids(QDD_LABELS)
    pilot_current_ids = ids(PILOT_CURRENT_LABELS)
    pilot_ever_props = [f"hs_v2_date_entered_{stages[l]}" for l in PILOT_EVER_LABELS if l in stages]

    props = ["dealstage", "business_unit", "demo_source_type",
             "meeting_date___time___sales", "owner_team"] + pilot_ever_props

    today_et = datetime.now(ET)
    start_ms = et_midnight_epoch_ms(datetime(YEAR, 1, 1).date())
    end_ms = et_midnight_epoch_ms(this_week_monday(today_et))   # < start of this week

    deals = fetch_deals(props, start_ms, end_ms)
    print(f"Pulled {len(deals)} deals.")

    # buckets[grain][bu][metric][period_key] = count
    def blank():
        return {m: {} for m in ("demos", "demos_nc", "dcc", "qdd", "pilots")}
    agg = {g: {"ACE": blank(), "SPADE": blank()} for g in ("weekly", "monthly")}

    for d in deals:
        p = d.get("properties", {})
        bu_raw = p.get("business_unit")
        if bu_raw not in ("true", "false"):
            continue
        bu = "ACE" if bu_raw == "true" else "SPADE"
        dt = parse_meeting(p.get("meeting_date___time___sales"))
        if dt is None:
            continue
        wk = (dt.date() - timedelta(days=dt.weekday())).isoformat()
        mo = f"{dt.year}-{dt.month:02d}-01"
        stage = p.get("dealstage")
        src = p.get("demo_source_type")
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
                bucket = agg[grain][bu][m]
                bucket[key] = bucket.get(key, 0) + 1

    # Build ordered period lists
    jan1_monday = (datetime(YEAR, 1, 1).date()
                   - timedelta(days=datetime(YEAR, 1, 1).weekday()))
    week_keys = sorted({k for bu in ("ACE", "SPADE") for m in agg["weekly"][bu]
                        for k in agg["weekly"][bu][m]})
    # drop the partial leading week (Monday < Jan 1)
    week_keys = [w for w in week_keys if datetime.fromisoformat(w).date() >= datetime(YEAR, 1, 1).date()
                 or datetime.fromisoformat(w).date() == jan1_monday and jan1_monday >= datetime(YEAR, 1, 1).date()]
    week_keys = [w for w in week_keys if datetime.fromisoformat(w).date() >= datetime(YEAR, 1, 1).date()]
    month_keys = sorted({k for bu in ("ACE", "SPADE") for m in agg["monthly"][bu]
                         for k in agg["monthly"][bu][m]})
    # Drop the current calendar month: it's incomplete (only week(s) before this
    # week) and its deals are too new to have converted, so its ratios are
    # artificially low and would misread as a conversion drop.
    current_month_key = f"{today_et.year}-{today_et.month:02d}-01"
    month_keys = [k for k in month_keys if k != current_month_key]

    def fmt_week(k):
        d = datetime.fromisoformat(k).date()
        return f"{d.month}/{d.day}"

    def fmt_month(k):
        return datetime.fromisoformat(k).strftime("%b")

    def series(grain, bu, metric, keys):
        b = agg[grain][bu][metric]
        return [b.get(k, 0) for k in keys]

    def pack(grain, keys):
        return {bu: {m: series(grain, bu, m, keys)
                     for m in ("demos", "demos_nc", "dcc", "qdd", "pilots")}
                for bu in ("ACE", "SPADE")}

    out = {
        "generated": datetime.now(ET).strftime("%Y-%m-%d %H:%M %Z"),
        "weekly": {"labels": [fmt_week(k) for k in week_keys], **pack("weekly", week_keys)},
        "monthly": {"labels": [fmt_month(k) for k in month_keys], **pack("monthly", month_keys)},
    }

    os.makedirs("site", exist_ok=True)
    favicon_uri = "data:image/svg+xml;base64," + base64.b64encode(FAVICON_SVG.encode()).decode()
    html = (TEMPLATE
            .replace("__FAVICON__", favicon_uri)
            .replace("/*__DATA__*/null", json.dumps(out)))
    with open("site/index.html", "w") as f:
        f.write(html)
    print(f"Wrote site/index.html ({out['generated']}).")


# Tab favicon: perched crow (option 1), static — browsers don't animate favicons.
FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<ellipse cx="30" cy="37" rx="15" ry="11" fill="#23262E"/>'
    '<circle cx="17" cy="25" r="8.5" fill="#23262E"/>'
    '<polygon points="9,23 1,26.5 9,30" fill="#D85A30"/>'
    '<polygon points="44,34 61,28 57,42" fill="#23262E"/>'
    '<circle cx="15" cy="23" r="1.8" fill="#F3F1EA"/>'
    '<path d="M31,30 C41,25 53,30 50,41 C43,43 34,39 29,32 Z" fill="#3A3F4A"/>'
    '</svg>'
)


# ---------------------------------------------------------------------------
# Report template (data injected at /*__DATA__*/null)
# ---------------------------------------------------------------------------
TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RevOps Conversion Report</title>
<link rel="icon" type="image/svg+xml" href="__FAVICON__">
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#2C2C2A;max-width:920px;margin:0 auto;padding:24px;background:#fff;}
h1{font-size:20px;font-weight:600;margin:0 0 4px;}
.tabs{display:flex;gap:4px;border-bottom:1px solid #D3D1C7;margin:14px 0 12px;}
.tb{padding:8px 16px;font-size:13px;font-weight:500;color:#5F5E5A;background:none;border:none;border-bottom:2px solid transparent;cursor:pointer;font-family:inherit;}
.tb:hover{color:#2C2C2A;}.tb.active{color:#185FA5;border-bottom-color:#185FA5;}
.controls{display:flex;flex-wrap:wrap;gap:18px;align-items:center;margin-bottom:6px;}
.seg{display:inline-flex;border:1px solid #D3D1C7;border-radius:6px;overflow:hidden;}
.sg{padding:6px 12px;font-size:12px;color:#5F5E5A;background:#fff;border:none;cursor:pointer;font-family:inherit;border-right:1px solid #D3D1C7;}
.sg:last-child{border-right:none;}.sg:hover{background:#F4F3EE;}.sg.active{background:#185FA5;color:#fff;}
.meta{font-size:11px;color:#888780;margin-bottom:14px;}
.ct{font-size:15px;font-weight:600;margin-bottom:4px;}
.lg{display:flex;flex-wrap:wrap;gap:14px;margin-bottom:6px;font-size:11px;color:#5F5E5A;}
.lg span{display:flex;align-items:center;gap:5px;}.lg i{width:15px;height:0;display:inline-block;}
.wrap{position:relative;width:100%;height:300px;margin-bottom:26px;}
.hdr{display:flex;align-items:center;gap:14px;}
.logo{flex:none;width:72px;height:72px;}
@keyframes flap5{0%,100%{transform:rotate(-14deg)}50%{transform:rotate(10deg)}}
@keyframes draw5{0%{stroke-dashoffset:90}60%,100%{stroke-dashoffset:0}}
.wing5{transform-origin:50px 15px;animation:flap5 0.65s ease-in-out infinite}
.line5{stroke-dasharray:90;animation:draw5 2.8s ease-in-out infinite}
</style></head><body>
<div class="hdr">
  <svg class="logo" viewBox="0 0 64 64" role="img" aria-label="crow perched atop a rising trend line">
    <polyline class="line5" points="5,55 20,47 34,49 49,20" fill="none" stroke="#185FA5" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
    <polygon points="44,16 37,13 44,20" fill="#23262E"/>
    <ellipse cx="50" cy="16" rx="6.5" ry="5" fill="#23262E"/>
    <circle cx="55" cy="12" r="4" fill="#23262E"/>
    <polygon points="59,11 65,12.5 59,14" fill="#D85A30"/>
    <circle cx="56" cy="11" r="1" fill="#F3F1EA"/>
    <line x1="48" y1="20" x2="47" y2="25" stroke="#23262E" stroke-width="1.6"/>
    <line x1="52" y1="20" x2="53" y2="25" stroke="#23262E" stroke-width="1.6"/>
    <path class="wing5" d="M50,15 C54,12 60,14 58,20 C54,21 50,19 48,16 Z" fill="#3A3F4A"/>
  </svg>
  <div>
    <h1>RevOps Weekly Conversion Report</h1>
    <div class="meta">Beam AI Deals &middot; calendar YTD &middot; excludes blank Business Unit &middot; <span id="gen"></span></div>
  </div>
</div>
<div class="tabs"><button class="tb active" data-u="Overall">Overall</button><button class="tb" data-u="ACE">ACE</button><button class="tb" data-u="SPADE">SPADE</button></div>
<div class="controls">
  <div class="seg" data-group="gran"><button class="sg active" data-v="weekly">Weekly</button><button class="sg" data-v="monthly">Monthly</button></div>
  <div class="seg" data-group="basis"><button class="sg active" data-v="with">Total incl. Cancelled</button><button class="sg" data-v="without">Total excl. Cancelled</button></div>
</div>
<div id="t1" class="ct"></div>
<div class="lg"><span><i style="border-top:2px solid #185FA5;"></i>DCC / total</span><span><i style="border-top:2px dashed #0F6E56;"></i>QDD / total</span><span><i style="border-top:2px dotted #D85A30;"></i>Pilots / total</span></div>
<div class="wrap"><canvas id="c1"></canvas></div>
<div class="ct">Conversion as % of DCC</div>
<div class="lg"><span><i style="border-top:2px dashed #0F6E56;"></i>QDD / DCC</span><span><i style="border-top:2px dotted #D85A30;"></i>Pilots / DCC</span></div>
<div class="wrap"><canvas id="c2"></canvas></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0/dist/chartjs-plugin-datalabels.min.js"></script>
<script>
Chart.register(ChartDataLabels);
const DATA = /*__DATA__*/null;
let gran='weekly',unit='Overall',basis='with';
document.getElementById('gen').textContent='updated '+DATA.generated;
const add=(a,b)=>a.map((v,i)=>v+b[i]);
const sel=(d,m)=>unit==='Overall'?add(d.ACE[m],d.SPADE[m]):d[unit][m];
const pct=(a,b)=>a.map((v,i)=>b[i]?Math.round(v/b[i]*1000)/10:null);
const ymax=arrs=>{let m=0;arrs.forEach(a=>a.forEach(v=>{if(v!=null&&v>m)m=v;}));return Math.min(100,Math.ceil((m+8)/10)*10);};
const opts=()=>({responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false,callbacks:{label:c=>c.dataset.label+': '+c.parsed.y+'%'}},datalabels:{display:gran==='monthly',align:'top',anchor:'end',offset:3,color:c=>c.dataset.borderColor,font:{size:9,weight:500},formatter:v=>v===null?'':v+'%'}},scales:{x:{ticks:{autoSkip:false,maxRotation:0,font:{size:10}},grid:{display:false}},y:{min:0,ticks:{callback:v=>v+'%'},grid:{color:'rgba(128,128,128,0.15)'}}}});
const mk=(id,ds)=>new Chart(document.getElementById(id),{type:'line',data:{labels:DATA.weekly.labels,datasets:ds},options:opts()});
const c1=mk('c1',[{label:'DCC / total',borderColor:'#185FA5',backgroundColor:'#185FA5',pointRadius:3,tension:0.3,data:[]},{label:'QDD / total',borderColor:'#0F6E56',backgroundColor:'#0F6E56',borderDash:[6,4],pointRadius:3,tension:0.3,data:[]},{label:'Pilots / total',borderColor:'#D85A30',backgroundColor:'#D85A30',borderDash:[2,3],pointRadius:4,tension:0.3,data:[]}]);
const c2=mk('c2',[{label:'QDD / DCC',borderColor:'#0F6E56',backgroundColor:'#0F6E56',borderDash:[6,4],pointRadius:3,tension:0.3,data:[]},{label:'Pilots / DCC',borderColor:'#D85A30',backgroundColor:'#D85A30',borderDash:[2,3],pointRadius:4,tension:0.3,data:[]}]);
function render(){
 const d=DATA[gran];
 const total=sel(d,basis==='with'?'demos':'demos_nc');
 const dcc=sel(d,'dcc'),qdd=sel(d,'qdd'),pil=sel(d,'pilots');
 const a1=[pct(dcc,total),pct(qdd,total),pct(pil,total)],a2=[pct(qdd,dcc),pct(pil,dcc)];
 [c1,c2].forEach(c=>{c.data.labels=d.labels;c.options.plugins.datalabels.display=(gran==='monthly');});
 c1.data.datasets.forEach((ds,i)=>ds.data=a1[i]);
 c2.data.datasets.forEach((ds,i)=>ds.data=a2[i]);
 c1.options.scales.y.max=ymax(a1);c2.options.scales.y.max=ymax(a2);
 c1.update();c2.update();
 document.getElementById('t1').textContent='Conversion as % of total demos ('+(basis==='with'?'incl.':'excl.')+' Cancelled)';
}
document.querySelectorAll('.tb').forEach(t=>t.addEventListener('click',()=>{document.querySelectorAll('.tb').forEach(x=>x.classList.remove('active'));t.classList.add('active');unit=t.dataset.u;render();}));
document.querySelectorAll('.seg').forEach(g=>g.querySelectorAll('.sg').forEach(b=>b.addEventListener('click',()=>{g.querySelectorAll('.sg').forEach(x=>x.classList.remove('active'));b.classList.add('active');if(g.dataset.group==='gran')gran=b.dataset.v;else basis=b.dataset.v;render();})));
render();
</script></body></html>
"""

if __name__ == "__main__":
    main()
