# RevOps Conversion Report — Railway (live, on-demand refresh)

A FastAPI web service that serves the interactive RevOps conversion report
(Demos -> DCC -> QDD -> Pilots, split Overall / ACE / SPADE, weekly + monthly,
incl./excl.-Cancelled toggle) and re-pulls live from HubSpot on demand.

- `GET /`        -> the report page (with the crow logo + favicon)
- `GET /data`    -> cached report data as JSON (auto-refreshes if older than 30 min)
- `POST /refresh`-> forces a live HubSpot pull and returns fresh data
  (this is what the on-page **Refresh** button calls)

## Files
- `app.py`          - the web service (routes + report page template)
- `report_data.py`  - HubSpot pull + metric computation (shared logic)
- `requirements.txt`- deps (fastapi, uvicorn, requests, tzdata)
- `Procfile` / `railway.toml` - tell Railway how to run it
- `generate_report.py` - OLD GitHub-Pages generator; not used by Railway (safe to delete)

## Deploy on Railway
1. **Make the repo private** (Railway needs no public access): GitHub repo ->
   Settings -> General -> Change visibility -> Private.
2. **Delete the old Pages workflow** so it stops failing daily on a private repo:
   delete `.github/workflows/refresh.yml`.
3. In Railway -> **New Project -> Deploy from GitHub repo** -> pick
   `RevOps-CRO-Report`. Railway auto-detects Python and the start command.
4. Project -> **Variables** -> add `HUBSPOT_TOKEN` = the HubSpot private-app token
   (scopes `crm.objects.deals.read`, `crm.schemas.deals.read`). Save; it redeploys.
5. Project -> **Settings -> Networking -> Generate Domain** -> that URL is the
   live report. Open it; it pulls live data on first load.

## Behaviour notes
- **Always current:** any visit older than 30 minutes triggers an automatic live
  pull, so the report is fresh whenever someone opens it - no fixed daily time
  needed. The **Refresh** button forces an instant live pull (takes a few seconds;
  the button spins while it works).
- **Timezone:** all date math (week/month buckets, YTD + "before this week"
  cutoffs) is anchored to **US/Eastern** to match HubSpot's account timezone.
- **Current month dropped:** the monthly view shows complete months only; the
  in-progress month is hidden because its new deals haven't matured and would read
  as a false conversion drop.
- **No access control:** the URL is open to anyone who has it. Add a password gate
  later if needed.
- **Pilots:** uses the true three-stage "has ever been" rule.

## Local test (optional)
```
pip install -r requirements.txt
export HUBSPOT_TOKEN=...        # your private-app token
uvicorn app:app --reload
# open http://localhost:8000
```
