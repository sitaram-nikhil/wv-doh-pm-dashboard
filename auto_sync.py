import urllib.request
import urllib.parse
import subprocess
import os

SPREADSHEET_ID = "1zRtwfMZceQPDkJIHz84yYmmvdMdG5isdznA7iY-3fAk"

SHEETS_TO_SYNC = {
    'Cameron': 'Dashboard_2026_Cameron.csv',
    'Jennifer': 'Dashboard_2026_Jennifer.csv',
    'Kyle': 'Dashboard_2026_Kyle.csv',
    'Kylena': 'Dashboard_2026_Kylena.csv',
    'Rhonda': 'Dashboard_2026_Rhonda.csv',
    'Sharonnia': 'Dashboard_2026_Sharonnia.csv',
    'Travis': 'Dashboard_2026_Travis.csv',
    'Complete': 'Dashboard_2026_Complete.csv',
    'Cancelled_Reallocated': 'Dashboard_2026_Cancelled_Reallocated.csv'
}

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

def sync_google_data():
    print("Syncing live project data from Google Sheets...")
    
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