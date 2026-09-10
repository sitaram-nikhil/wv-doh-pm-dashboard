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

def get_col_val(row, *target_names):
    """
    Robust column lookup matching column names regardless of embedded newlines or spaces.
    e.g., 'STATE PROJECT\nNUMBER' matches 'STATE PROJECT NUMBER'.
    """
    for col in row.keys():
        norm_key = re.sub(r'\s+', '', str(col)).upper()
        for target in target_names:
            norm_target = re.sub(r'\s+', '', str(target)).upper()
            if norm_key == norm_target:
                val = row[col]
                if pd.notna(val):
                    return str(val).strip()
    return ''

def clean_currency(val_str):
    if not val_str:
        return 0.0
    lines = [line.strip() for line in val_str.split('\n') if line.strip()]
    if not lines:
        return 0.0
    first_line = lines[0]
    cleaned = re.sub(r'[^\d.]', '', first_line)
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0

def clean_completion_pct(val_str):
    if not val_str:
        return "0%"
    
    val_clean = str(val_str).strip()
    if not val_clean or val_clean.lower() in ['nan', 'null', 'none', '-', 'tba', 'tbd', 'yes', 'no']:
        return "0%"
    
    # Ignore target dates logged in % columns (e.g., "12/28/26 E", "2025-10-01")
    if re.search(r'\d{1,4}[-/]\d{1,2}[-/]\d{1,4}', val_clean):
        return "0%"
    
    # Match explicit % strings (e.g., "95%", "25.5%", "0.25%")
    match_pct = re.search(r'(\d+(\.\d+)?)%', val_clean)
    if match_pct:
        num = float(match_pct.group(1))
        if 0 < num <= 1.0:
            num = num * 100
        return f"{min(100, round(num))}%"
    
    # Scale decimal floats (e.g., "0.95" -> 95%, "0.25" -> 25%)
    match_num = re.search(r'^\s*(\d+(\.\d+)?)\s*$', val_clean)
    if match_num:
        num = float(match_num.group(1))
        if 0 < num <= 1.0:
            num = num * 100
        elif num > 100:
            num = 100.0
        return f"{min(100, round(num))}%"
        
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

            for idx, row in df.iterrows():
                proj_name = get_col_val(row, 'PROJECT NAME', 'NAME')
                if not proj_name:
                    continue

                proj_dict = row.to_dict()

                # Robust column extraction
                state_num = get_col_val(row, 'STATE PROJECT NUMBER', 'STATE PROJECT NO', 'STATE PROJ NUM')
                prog_num = get_col_val(row, 'PROGRAM NUMBER', 'PROGRAM NO', 'PROGRAM NUM')
                proj_type = get_col_val(row, 'PROJECT TYPE', 'TYPE')
                fed_num = get_col_val(row, 'FEDERAL PROJECT NUMBER', 'FEDERAL PROJ NUM')
                raw_award = get_col_val(row, 'AWARD')
                raw_supp = get_col_val(row, 'SUPPLEMENTALS', 'SUPPLEMENTAL')
                raw_pct = get_col_val(row, 'PROJECT COMPLETION PERCENTAGE', 'COMPLETION PERCENTAGE', 'PERCENTAGE', '% COMPLETE')

                # Clean Currency Fields
                award_clean = clean_currency(raw_award)
                supp_clean = clean_currency(raw_supp)
                total_val_clean = award_clean + supp_clean

                # Clean Completion Percentage
                clean_pct = clean_completion_pct(raw_pct)
                proj_dict['PROJECT COMPLETION PERCENTAGE'] = clean_pct

                # Generate Clean State Project Identifier
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
                proj_dict['STATE PROJECT NUMBER'] = state_num if state_num else clean_num
                proj_dict['PROGRAM NUMBER'] = prog_num
                proj_dict['PROGRAM_NUM_CLEAN'] = prog_num.replace('.0', '').strip()
                proj_dict['FED_NUM_CLEAN'] = fed_num
                proj_dict['PROJECT TYPE'] = proj_type
                proj_dict['PROJECT_TYPE_CLEAN'] = proj_type
                proj_dict['SOURCE_PM'] = pm_tag

                # Replace NaNs with None for JSON compliance
                for k, v in proj_dict.items():
                    if pd.isna(v):
                        proj_dict[k] = None

                all_projects.append(proj_dict)

            print(f"  [✓] Processed {len(df)} rows from {filename}")

        except Exception as e:
            print(f"  [×] Error reading {filename}: {e}")

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