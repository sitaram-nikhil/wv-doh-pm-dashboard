"""
Downloads the TA/RT project tabs and the FMIS inactive list from Google Sheets,
checks each download, then rebuilds dashboard_data.js.

What changed from the old version:
  1. Tabs are fetched by their fixed tab ID (gid), not by name. If a tab name
     is wrong, Google quietly sends the first tab instead, which is how the
     Complete tab ended up counted a second time as "Cancelled".
     Tabs now use Google's plain "export" download instead of the "gviz"
     query download. The gviz download guesses one data type per column and
     blanks out any cell that doesn't fit (for example "N/A" in a date column,
     or "2012 / 2024" in Award Year), and it dropped 9 of Sharonnia's 45 rows.
     The export download returns exactly what is typed in the sheet, and a
     wrong tab ID gives an error instead of a different tab.
  2. Every download is checked before it replaces the old file. A bad download
     (error page, wrong tab, empty file) keeps the last good copy.
  3. Results are written to sync_status.js so the dashboard can show when the
     data was last updated and how many projects came from each tab.
  4. The Cancelled/Reallocated and CDS Projects tabs are no longer downloaded
     (decision 2026-11-12: leave them off the dashboard).
"""
import csv
import io
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

# Master Google Sheet for the project manager and Complete tabs
SPREADSHEET_ID = "1zRtwfMZceQPDkJIHz84yYmmvdMdG5isdznA7iY-3fAk"

# Tab name -> (tab ID, local file). Tab IDs come from the "gid=" part of the
# sheet's web address. They do not change when a tab is renamed or moved.
SHEETS_TO_SYNC = {
    "Cameron":   ("819828827",  "Dashboard_2026_Cameron.csv"),
    "Jennifer":  ("1529913818", "Dashboard_2026_Jennifer.csv"),
    "Kyle":      ("899958113",  "Dashboard_2026_Kyle.csv"),
    "Kylena":    ("1505086908", "Dashboard_2026_Kylena.csv"),
    "Rhonda":    ("677698412",  "Dashboard_2026_Rhonda.csv"),
    "Sharonnia": ("787950147",  "Dashboard_2026_Sharonnia.csv"),
    "Travis":    ("774875965",  "Dashboard_2026_Travis.csv"),
    "Brian":     ("1512600683", "Dashboard_2026_Brian.csv"),
    "Complete":  ("964637556",  "Dashboard_2026_Complete.csv"),
}

# Central Financial Inactive Master Sheet (separate Google Sheet)
FINANCIAL_SHEET_ID = "1pnP8rTiJw5tG4oEVtJV2ErrUCqHinQ1oM7vnSXnnOks"
FINANCIAL_GID = "697686555"
FINANCIAL_LOCAL_FILENAME = "Inactive_120PED_Inactive.csv"

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
STATUS_FILE = os.path.join(PROJECT_DIR, "sync_status.js")


def project_tab_url(gid):
  return (f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}"
          f"/export?format=csv&gid={gid}")


def financial_url():
  return (f"https://docs.google.com/spreadsheets/d/{FINANCIAL_SHEET_ID}"
          f"/export?format=csv&gid={FINANCIAL_GID}")


def download_text(url):
  req = urllib.request.Request(url, headers={"User-Agent": "wv-doh-pm-dashboard-sync"})
  with urllib.request.urlopen(req, timeout=60) as resp:
    return resp.read().decode("utf-8-sig")


def clean_header(cell):
  return " ".join(str(cell).split()).upper()


def check_project_tab(text):
  """Returns (number of projects, problem or None)."""
  if text.lstrip().startswith("<"):
    return 0, "Google sent a web page instead of data (the sheet may not be shared publicly)"
  rows = list(csv.reader(io.StringIO(text)))
  if not rows:
    return 0, "the download was empty"
  header = [clean_header(c) for c in rows[0]]
  if "PROJECT NAME" not in header:
    return 0, "the tab has no PROJECT NAME column (wrong tab or the header row moved)"
  name_col = header.index("PROJECT NAME")
  count = sum(1 for r in rows[1:] if len(r) > name_col and r[name_col].strip())
  return count, None


def check_financial(text):
  if text.lstrip().startswith("<"):
    return 0, "Google sent a web page instead of data (the sheet may not be shared publicly)"
  rows = list(csv.reader(io.StringIO(text)))
  if not rows or "INACTIVE Y/N" not in [clean_header(c) for c in rows[0]]:
    return 0, "the file has no 'Inactive Y/N' column (wrong tab or the header row moved)"
  return sum(1 for r in rows[1:] if any(c.strip() for c in r)), None


def sync_one(label, url, local_filename, checker):
  """Downloads one tab. Replaces the local file only if the download passes its check."""
  out_path = os.path.join(PROJECT_DIR, local_filename)
  entry = {"tab": label, "file": local_filename}
  try:
    text = download_text(url)
    count, problem = checker(text)
  except Exception as e:  # network error, 404, timeout
    count, problem = 0, f"download failed ({e})"

  if problem is None:
    with open(out_path, "w", encoding="utf-8", newline="") as f:
      f.write(text)
    entry.update(ok=True, rows=count, note="")
    print(f"  [OK]   {label}: {count} rows")
  else:
    kept = os.path.exists(out_path)
    entry.update(ok=False, rows=None,
                 note=problem + ("; showing the last good copy" if kept else "; no earlier copy available"))
    print(f"  [FAIL] {label}: {entry['note']}")
    # Shows as a red error line in the GitHub Actions log
    print(f"::error title=Sync failed for {label}::{entry['note']}")
  return entry


def write_status(results, build_ok):
  status = {
      "synced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
      "all_ok": build_ok and all(r["ok"] for r in results),
      "build_ok": build_ok,
      "tabs": results,
  }
  with open(STATUS_FILE, "w", encoding="utf-8") as f:
    f.write("// Written by auto_sync.py. Do not edit by hand.\n")
    f.write("window.SYNC_STATUS = " + json.dumps(status, indent=2) + ";\n")


def sync_google_data():
  print("Syncing live project data from Google Sheets...")
  results = [sync_one("FMIS inactive list", financial_url(),
                      FINANCIAL_LOCAL_FILENAME, check_financial)]
  for tab_name, (gid, local_filename) in SHEETS_TO_SYNC.items():
    results.append(sync_one(tab_name, project_tab_url(gid), local_filename, check_project_tab))

  print("\nProcessing spreadsheets into dashboard_data.js...")
  build_script = os.path.join(PROJECT_DIR, "build_dashboard_data.py")
  build = subprocess.run([sys.executable, build_script], cwd=PROJECT_DIR)
  build_ok = build.returncode == 0
  if not build_ok:
    print("::error title=Build failed::build_dashboard_data.py stopped with an error; "
          "dashboard_data.js was not updated")

  write_status(results, build_ok)
  failed = [r["tab"] for r in results if not r["ok"]]
  print(f"\nDone. {len(results) - len(failed)} of {len(results)} downloads OK."
        + (f" Problems: {', '.join(failed)}" if failed else ""))
  # Exit 0 even with problems so the workflow still commits sync_status.js,
  # which is how the dashboard shows the warning.


if __name__ == "__main__":
  sync_google_data()
