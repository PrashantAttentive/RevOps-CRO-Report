# RevOps Conversion Report — auto-refreshing on GitHub

A self-contained interactive report (Demos → DCC → QDD → Pilots conversion rates,
split Overall / ACE / SPADE, weekly + monthly, with an incl./excl.-Cancelled
toggle) that **regenerates itself every day at 3:00 PM IST** from live HubSpot
data and publishes to GitHub Pages.

No server, no cost. The data is pulled by a scheduled GitHub Action, computed in
Python, and baked into `site/index.html`, which Pages serves.

---

## What you need once

1. A **HubSpot private-app token** with scopes `crm.objects.deals.read` and
   `crm.schemas.deals.read`.
2. A **GitHub account** (free).

---

## Setup (about 10 minutes)

### 1. Create the HubSpot token
HubSpot → **Settings (gear)** → **Integrations → Private Apps** →
**Create a private app** → name it "RevOps Report" → **Scopes** tab → tick
`crm.objects.deals.read` and `crm.schemas.deals.read` → **Create app** → copy the
**access token**. Keep it handy; you'll paste it into GitHub next (never into the
code).

### 2. Create the repository
GitHub → **+** (top right) → **New repository** → name `revops-report` →
**Private** → **Create repository**.

### 3. Add these files
On the empty repo page, use **"uploading an existing file"** and drag in
everything from this folder, preserving the structure:
```
generate_report.py
requirements.txt
README.md
.github/workflows/refresh.yml
```
(The `.github/workflows/` path matters — keep it exactly.) Commit.

### 4. Add the token as a secret
Repo → **Settings → Secrets and variables → Actions → New repository secret** →
Name: `HUBSPOT_TOKEN` → Value: the token from step 1 → **Add secret**.

### 5. Turn on Pages (GitHub Actions mode)
Repo → **Settings → Pages** → under **Build and deployment → Source**, choose
**GitHub Actions**. (No branch selection needed.)

### 6. Run it once
Repo → **Actions** tab → select **Refresh RevOps Report** → **Run workflow** →
**Run workflow**. Wait ~1–2 minutes. When it finishes green, the run summary
shows your live URL (also under **Settings → Pages**).

That's it. From now on it refreshes automatically every day at ~3 PM IST, and you
can hit **Run workflow** any time for an on-demand refresh.

---

## Notes / honest caveats

- **Timing:** GitHub's scheduler can fire 5–15 min late under load, occasionally
  more. If it must be done before a 3 PM meeting, change the cron in
  `refresh.yml` to `0 9 * * *` (2:30 PM IST) for a buffer.
- **Timezones are intentionally two different things:** the *schedule* is
  09:30 UTC (3 PM IST); the *data math* (week/month buckets, the year-to-date and
  "before this week" cutoffs) is anchored to **US/Eastern**, because that's the
  timezone your HubSpot account evaluates dates in. Don't "fix" one to match the
  other.
- **Privacy:** GitHub Pages is **public** — anyone with the URL can view the
  report (the URL is unguessable, but it is not access-controlled). If this data
  must be private, this is the point to move to a host that supports a password
  gate (e.g. Railway).
- **First-run reconciliation:** the very first real run is also the first time
  this code touches live HubSpot. Compare its numbers against a fresh manual pull
  to confirm they line up (expect Pilots to be ~1 higher than the chat preview —
  this code uses the exact three-stage "has ever been" rule, which is correct).
- **10k ceiling:** HubSpot search returns at most 10,000 records per query. The
  in-scope yearly volume is well under this; if it ever approaches it, the pull
  needs to be chunked by date (the script prints a WARNING if it gets close).

## To change things later
- Schedule → edit the `cron` line in `.github/workflows/refresh.yml`.
- Weekly per-point labels → in `generate_report.py`, the `datalabels.display`
  currently shows labels on monthly only; set it to `true` to always show.
- Drop/keep the partial first week → handled in `main()` where `week_keys` is
  filtered to dates on/after Jan 1.
