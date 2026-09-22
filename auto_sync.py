import os
import subprocess
import urllib.parse
import urllib.request

# Master Google Sheet ID for PM and Portfolio Tabs
SPREADSHEET_ID = "1zRtwfMZceQPDkJIHz84yYmmvdMdG5isdznA7iY-3fAk"

# Central Financial Inactive Master Sheet (Separate Google Sheet)
FINANCIAL_SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1pnP8rTiJw5tG4oEVtJV2ErrUCqHinQ1oM7vnSXnnOks/export?format=csv&gid=697686555"
FINANCIAL_LOCAL_FILENAME = "Inactive_120PED_Inactive.csv"

SHEETS_TO_SYNC = {
    'Cameron': 'Dashboard_2026_Cameron.csv',
    'Jennifer': 'Dashboard_2026_Jennifer.csv',
    'Kyle': 'Dashboard_2026_Kyle.csv',
    'Kylena': 'Dashboard_2026_Kylena.csv',
    'Rhonda': 'Dashboard_2026_Rhonda.csv',
    'Sharonnia': 'Dashboard_2026_Sharonnia.csv',
    'Travis': 'Dashboard_2026_Travis.csv',
    'Brian': 'Dashboard_2026_Brian.csv',
    'Complete': 'Dashboard_2026_Complete.csv',
    'Cancelled_Reallocated': 'Dashboard_2026_Cancelled_Reallocated.csv',
}

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


def sync_google_data():
  print("Syncing live project data from Google Sheets...")

  # 1. Sync Central Financial Master Spreadsheet
  fin_out_path = os.path.join(PROJECT_DIR, FINANCIAL_LOCAL_FILENAME)
  try:
    urllib.request.urlretrieve(FINANCIAL_SPREADSHEET_URL, fin_out_path)
    print(f"  [✓] Downloaded {FINANCIAL_LOCAL_FILENAME}")
  except Exception as e:
    print(
        f"  [×] Error downloading financial sheet ({FINANCIAL_LOCAL_FILENAME}):"
        f" {e}"
    )

  # 2. Sync PM & Portfolio Tabs
  for tab_name, local_filename in SHEETS_TO_SYNC.items():
    csv_url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/gviz/tq?tqx=out:csv&sheet={urllib.parse.quote(tab_name)}"
    out_path = os.path.join(PROJECT_DIR, local_filename)
    try:
      urllib.request.urlretrieve(csv_url, out_path)
      print(f"  [✓] Downloaded {local_filename}")
    except Exception as e:
      print(f"  [×] Error downloading {tab_name}: {e}")

  print("\nProcessing spreadsheets into dashboard_data.js...")
  processor_script = os.path.join(PROJECT_DIR, "build_dashboard_data.py")
  subprocess.run(["python", processor_script], check=True)


if __name__ == "__main__":
  sync_google_data()