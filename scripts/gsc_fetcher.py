"""Fetch Google Search Console data and POST to translationchina.com ingest endpoint.

Runs daily via GitHub Actions (server is in China — can't reach Google directly).

Env vars expected:
  GSC_SA_KEY_JSON     — full JSON content of the SA key file
  TC_INGEST_TOKEN     — shared secret for the ingest endpoint
  TC_INGEST_URL       — defaults to https://admin.translationchina.com/api/analytics/_gsc-ingest

Usage local-dev:
  set GSC_SA_KEY_JSON  to file content
  set TC_INGEST_TOKEN  to the token
  python gsc_fetcher.py
"""
import os, sys, json, datetime, time
import urllib.request, urllib.error
from google.oauth2 import service_account
from googleapiclient.discovery import build

INGEST_URL = os.environ.get('TC_INGEST_URL', 'https://admin.translationchina.com/api/analytics/_gsc-ingest')
SCOPES = ['https://www.googleapis.com/auth/webmasters.readonly']

DIMENSIONS = ['query', 'page', 'country', 'device']
ROW_LIMIT = 25000   # GSC max
DAYS_BACK = 28      # GSC API limit is 16 months but 28 days is rich enough


def load_creds():
    raw = os.environ.get('GSC_SA_KEY_JSON', '')
    if raw:
        info = json.loads(raw)
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    path = os.environ.get('GSC_SA_KEY_PATH', '')
    if path:
        return service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
    raise RuntimeError('No SA credentials — set GSC_SA_KEY_JSON or GSC_SA_KEY_PATH')


def fetch_site(svc, site_url, days_back=DAYS_BACK):
    today = datetime.date.today()
    start = today - datetime.timedelta(days=days_back)
    end = today - datetime.timedelta(days=2)  # GSC has ~2-day data lag

    results = {}
    for dim in DIMENSIONS:
        body = {
            'startDate': start.isoformat(),
            'endDate':   end.isoformat(),
            'dimensions': [dim],
            'rowLimit':  ROW_LIMIT,
            'dataState': 'final',
        }
        try:
            resp = svc.searchanalytics().query(siteUrl=site_url, body=body).execute()
        except Exception as e:
            print(f'  ! {site_url} dim={dim}: {e}', flush=True)
            continue
        rows = []
        for r in resp.get('rows', []):
            val = r['keys'][0]
            rows.append({
                'date':        end.isoformat(),    # aggregated for this period — use end date
                'value':       val,
                'impressions': r.get('impressions', 0),
                'clicks':      r.get('clicks', 0),
                'position':    r.get('position'),
                'ctr':         r.get('ctr'),
            })
        results[dim] = rows
        print(f'  ✓ {site_url} dim={dim}: {len(rows)} rows', flush=True)

    # Also fetch daily totals (no dimension) for time series
    body = {
        'startDate': start.isoformat(),
        'endDate':   end.isoformat(),
        'dimensions': ['date'],
        'rowLimit':  ROW_LIMIT,
        'dataState': 'final',
    }
    try:
        resp = svc.searchanalytics().query(siteUrl=site_url, body=body).execute()
        rows = []
        for r in resp.get('rows', []):
            rows.append({
                'date':        r['keys'][0],
                'value':       'TOTAL',
                'impressions': r.get('impressions', 0),
                'clicks':      r.get('clicks', 0),
                'position':    r.get('position'),
                'ctr':         r.get('ctr'),
            })
        results['date'] = rows
        print(f'  ✓ {site_url} dim=date: {len(rows)} rows', flush=True)
    except Exception as e:
        print(f'  ! {site_url} dim=date: {e}', flush=True)

    return results


def post_to_ingest(payload):
    token = os.environ.get('TC_INGEST_TOKEN', '')
    if not token:
        raise RuntimeError('TC_INGEST_TOKEN not set')
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        INGEST_URL, data=body, method='POST',
        headers={
            'Content-Type':   'application/json',
            'X-Ingest-Token': token,
        }
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read())
    return resp


def main():
    creds = load_creds()
    svc = build('searchconsole', 'v1', credentials=creds, cache_discovery=False)
    print(f'SA email: {creds.service_account_email}', flush=True)

    sites = svc.sites().list().execute().get('siteEntry', [])
    print(f'Found {len(sites)} accessible sites:', flush=True)
    for s in sites:
        print(f'  - {s["siteUrl"]}  ({s["permissionLevel"]})', flush=True)

    total_rows = 0
    for s in sites:
        url = s['siteUrl']
        if s.get('permissionLevel') in ('siteUnverifiedUser',):
            print(f'  skip unverified: {url}', flush=True); continue
        print(f'\n=== Fetching {url} ===', flush=True)
        site_data = fetch_site(svc, url)
        # POST one site at a time (avoid 413 on huge payloads)
        payload = {'data': {url: site_data}}
        try:
            resp = post_to_ingest(payload)
            print(f'  → ingest: {resp}', flush=True)
            total_rows += resp.get('rows_ingested', 0)
        except Exception as e:
            print(f'  ! ingest failed: {e}', flush=True)
    print(f'\n=== Done. Total rows ingested: {total_rows} ===', flush=True)


if __name__ == '__main__':
    main()
