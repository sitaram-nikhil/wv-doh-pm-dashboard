import os
import re
import json
import pandas as pd

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

SHEETS_TO_PROCESS = [
    ('Cameron', 'Dashboard_2026_Cameron.csv'),
    ('Jennifer', 'Dashboard_2026_Jennifer.csv'),
    ('Kyle', 'Dashboard_2026_Kyle.csv'),
    ('Kylena', 'Dashboard_2026_Kylena.csv'),
    ('Rhonda', 'Dashboard_2026_Rhonda.csv'),
    ('Sharonnia', 'Dashboard_2026_Sharonnia.csv'),
    ('Travis', 'Dashboard_2026_Travis.csv'),
    ('Brian', 'Dashboard_2026_Brian.csv'),
    ('Completed', 'Dashboard_2026_Complete.csv'),
    ('Cancelled', 'Dashboard_2026_Cancelled_Reallocated.csv')
]

def clean_currency(val):
    if pd.isna(val):
        return 0.0
    val_str = str(val).strip()
    # Handle multiline currency values (e.g., "$77,262.45\n\n$400,000.00") by picking first valid line
    lines = [line.strip() for line in val_str.split('\n') if line.strip()]
    if not lines:
        return 0.0
    first_line = lines[0]
    cleaned = re.sub(r'[^\d.]', '', first_line)
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0

def clean_completion_pct(val):
    if pd.isna(val):
        return "0%"
    val_str = str(val).strip()
    # Check if there is a numeric percentage pattern (e.g., "95%")
    match = re.search(r'(\d+(\.\d+)?)%', val_str)
    if match:
        return f"{match.group(1)}%"
    # Check if there is a raw integer/float (e.g., "95" or "95.0")
    match_raw = re.match(r'^\d+(\.\d+)?$', val_str)
    if match_raw:
        return f"{match_raw.group(0)}%"
    # If cell contains target dates (e.g., "12/28/26 E") or "TBA", safely default to "0%"
    return "0%"

def process_all_sheets():
    print("Processing local CSV spreadsheets into dashboard_data.js...")
    all_projects = []

    for pm_tag, filename in SHEETS_TO_PROCESS:
        filepath = os.path.join(PROJECT_DIR, filename)
        if not os.path.exists(filepath):
            print(f"  [!] Missing file: {filename} (skipping)")
            continue

        try:
            df = pd.read_csv(filepath)
            df.columns = [str(c).strip() for c in df.columns]

            for idx, row in df.iterrows():
                proj_name = row.get('PROJECT NAME', '')
                if pd.isna(proj_name) or str(proj_name).strip() == '':
                    continue

                proj_dict = row.to_dict()

                # Clean Currency Fields
                award_clean = clean_currency(row.get('AWARD', 0.0))
                supp_clean = clean_currency(row.get('SUPPLEMENTALS', 0.0))
                total_val_clean = award_clean + supp_clean

                # Clean Completion Percentage
                pct_col = [c for c in df.columns if 'COMPLETION' in c or 'PERCENTAGE' in c]
                raw_pct = row.get(pct_col[0], '0%') if pct_col else '0%'
                proj_dict['PROJECT COMPLETION PERCENTAGE'] = clean_completion_pct(raw_pct)

                # Generate Clean State Project Identifier
                state_num = str(row.get('STATE PROJECT NUMBER', '')).strip()
                if not state_num or state_num.lower() in ['nan', 'null', 'n/a', 'none', '']:
                    clean_num = f"PROJ-{pm_tag.upper()}-{idx+1}"
                else:
                    clean_num = re.sub(r'\s+', '', state_num)

                # Standardized Normalized Attributes
                proj_dict['AWARD_CLEAN'] = award_clean
                proj_dict['SUPPLEMENTAL_CLEAN'] = supp_clean
                proj_dict['TOTAL_VALUE_CLEAN'] = total_val_clean
                proj_dict['SPENT_DESIGN_CLEAN'] = 0.0
                proj_dict['SPENT_CONST_CLEAN'] = 0.0
                proj_dict['CLEAN_NUM'] = clean_num
                proj_dict['PROGRAM_NUM_CLEAN'] = str(row.get('PROGRAM NUMBER', '')).replace('.0', '').strip()
                proj_dict['FED_NUM_CLEAN'] = str(row.get('FEDERAL PROJECT NUMBER', '')).strip()
                proj_dict['PROJECT_TYPE_CLEAN'] = str(row.get('PROJECT TYPE', '')).strip()
                proj_dict['SOURCE_PM'] = pm_tag

                # Replace NaNs with None for JSON compliance
                for k, v in proj_dict.items():
                    if pd.isna(v):
                        proj_dict[k] = None

                all_projects.append(proj_dict)

            print(f"  [✓] Processed {len(df)} rows from {filename}")

        except Exception as e:
            print(f"  [×] Error reading {filename}: {e}")

    # Preserve existing GeoJSON if available inside current dashboard_data.js
    existing_geojson = {"type": "FeatureCollection", "features": []}
    js_out_path = os.path.join(PROJECT_DIR, "dashboard_data.js")

    if os.path.exists(js_out_path):
        try:
            with open(js_out_path, "r", encoding="utf-8") as f:
                content = f.read()
                match = re.search(r"const\s+DASHBOARD_DATA\s*=\s*(\{.*\});?", content, re.DOTALL)
                if match:
                    data_obj = json.loads(match.group(1))
                    if "geojson" in data_obj:
                        existing_geojson = data_obj["geojson"]
        except Exception:
            pass

    output_data = {
        "projects": all_projects,
        "geojson": existing_geojson
    }

    with open(js_out_path, "w", encoding="utf-8") as f:
        f.write("const DASHBOARD_DATA = ")
        json.dump(output_data, f, indent=2)
        f.write(";\n")

    print(f"\nSuccessfully compiled {len(all_projects)} project records into dashboard_data.js")

if __name__ == "__main__":
    process_all_sheets()