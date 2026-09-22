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

FINANCIAL_SPREADSHEET = 'Inactive_120PED_Inactive.csv'

PM_ALIAS_MAP = {
    'cameron': 'Cameron',
    'cameron hunt': 'Cameron',
    'hunt': 'Cameron',
    
    'jennifer': 'Jennifer',
    'jennifer ballard': 'Jennifer',
    'ballard': 'Jennifer',
    
    'kyle': 'Kyle',
    'kyle oliver': 'Kyle',
    'oliver': 'Kyle',
    
    'kylena': 'Kylena',
    'kylena nunnally': 'Kylena',
    'nunnally': 'Kylena',
    
    'rhonda': 'Rhonda',
    'rhonda brisendine': 'Rhonda',
    'brisendine': 'Rhonda',
    
    'sharonnia': 'Sharonnia',
    'sharonnia osayaba': 'Sharonnia',
    'osayaba': 'Sharonnia',
    
    'travis': 'Travis',
    'travis hayes': 'Travis',
    'hayes': 'Travis',
    
    'brian': 'Brian',
    'brian chapman': 'Brian',
    'b. chapman': 'Brian',
    'chapman': 'Brian',
    
    'mark scoular': 'Mark Scoular (Retd)',
    'mark scoular ( retd )': 'Mark Scoular (Retd)',
    'mark scoular (retd)': 'Mark Scoular (Retd)',
    'scoular': 'Mark Scoular (Retd)',
    
    'scott mcclanahan': 'Scott McClanahan (Retd)',
    'scott mcclanahan ( retd )': 'Scott McClanahan (Retd)',
    'scott mcclanahan (retd)': 'Scott McClanahan (Retd)',
    'mcclanahan': 'Scott McClanahan (Retd)'
}

def sanitize_fin_proj(val):
    """
    Cleans financial sheet 'PROGRAM' and 'Project #' values.
    Expands scientific notation floats (e.g., '2.02204e+06' -> '2022046'),
    removes trailing '.0', and strips non-alphanumeric characters.
    """
    if pd.isna(val) or val is None:
        return ''
    s = str(val).strip()
    if s.endswith('.0'):
        s = s[:-2]
    try:
        f = float(s)
        s = str(int(f))
    except ValueError:
        pass
    return re.sub(r'[^A-Za-z0-9]', '', s).upper()

def sanitize_pm_fed(val):
    """
    Cleans PM sheet 'FEDERAL PROJECT NUMBER' values by stripping
    punctuation (dashes, slashes, spaces, parentheses) and converting to uppercase.
    """
    if pd.isna(val) or val is None:
        return ''
    s = str(val).strip()
    return re.sub(r'[^A-Za-z0-9]', '', s).upper()

def extract_digit_sequences(val):
    """Extracts numeric clusters from formatted strings to enable token matching."""
    if pd.isna(val) or val is None:
        return set()
    clusters = re.findall(r'\d+', str(val))
    results = set(clusters)
    for i in range(len(clusters) - 1):
        results.add(clusters[i] + clusters[i + 1])
    return results

def normalize_pm_name(raw_name, fallback_tag):
    if not raw_name or str(raw_name).lower() in ['nan', 'null', 'none', 'unassigned', '']:
        lookup_key = str(fallback_tag).strip().lower()
    else:
        lookup_key = str(raw_name).strip().lower()
        
    return PM_ALIAS_MAP.get(lookup_key, raw_name.strip() if raw_name else fallback_tag)

def get_col_val(row, *target_names):
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
    
    if re.search(r'\d{1,4}[-/]\d{1,2}[-/]\d{1,4}', val_clean):
        return "0%"
    
    match_pct = re.search(r'(\d+(\.\d+)?)%', val_clean)
    if match_pct:
        num = float(match_pct.group(1))
        if 0 < num <= 1.0:
            num = num * 100
        return f"{min(100, round(num))}%"
    
    match_num = re.search(r'^\s*(\d+(\.\d+)?)\s*$', val_clean)
    if match_num:
        num = float(match_num.group(1))
        if 0 < num <= 1.0:
            num = num * 100
        elif num > 100:
            num = 100.0
        return f"{min(100, round(num))}%"
        
    return "0%"

def load_fmis_status_map():
    program_map = {}
    fin_filepath = os.path.join(PROJECT_DIR, FINANCIAL_SPREADSHEET)
    if not os.path.exists(fin_filepath):
        print(f"  [!] Financial sheet missing at {FINANCIAL_SPREADSHEET}. Defaulting unmatched FMIS statuses to 'N/A'.")
        return program_map

    try:
        df_fin = pd.read_csv(fin_filepath, dtype=str, on_bad_lines='skip')
        for _, row in df_fin.iterrows():
            clean_prog = sanitize_fin_proj(row.get('PROGRAM'))
            clean_proj = sanitize_fin_proj(row.get('Project #'))
            raw_inactive = str(row.get('Inactive Y/N', '')).strip().upper()

            status = 'Inactive' if raw_inactive == 'Y' else ('Active' if raw_inactive == 'N' else 'N/A')

            if clean_prog and clean_proj:
                if clean_prog not in program_map:
                    program_map[clean_prog] = []
                program_map[clean_prog].append((clean_proj, status))
        print(f"  [✓] Loaded {len(program_map)} program keys from {FINANCIAL_SPREADSHEET}")
    except Exception as e:
        print(f"  [×] Error loading financial spreadsheet: {e}")

    return program_map

def match_fmis_program_level(program_map, raw_pm_prog, raw_pm_fed):
    clean_prog = sanitize_fin_proj(raw_pm_prog)
    if not clean_prog or clean_prog not in program_map:
        return 'N/A'

    fin_records = program_map[clean_prog]
    clean_fed = sanitize_pm_fed(raw_pm_fed)
    pm_digits = extract_digit_sequences(raw_pm_fed)

    # 1. Exact cleaned match
    for fin_proj, status in fin_records:
        if fin_proj == clean_fed:
            return status

    # 2. Substring containment match
    for fin_proj, status in fin_records:
        if fin_proj in clean_fed or clean_fed in fin_proj:
            return status

    # 3. Digit sequence token match
    for fin_proj, status in fin_records:
        if fin_proj in pm_digits:
            return status
        for d in pm_digits:
            if len(fin_proj) >= 4 and len(d) >= 4:
                if fin_proj.endswith(d) or d.endswith(fin_proj) or fin_proj[-4:] == d[-4:]:
                    return status

    # 4. Program-level consensus fallback
    statuses = set(s for _, s in fin_records)
    if len(statuses) == 1:
        return list(statuses)[0]

    return 'N/A'

def process_all_sheets():
    print("Processing local CSV spreadsheets into dashboard_data.js...")
    program_map = load_fmis_status_map()
    all_projects = []

    for pm_tag, filename in SHEETS_TO_PROCESS:
        filepath = os.path.join(PROJECT_DIR, filename)
        if not os.path.exists(filepath):
            print(f"  [!] Missing file: {filename} (skipping)")
            continue

        try:
            df = pd.read_csv(filepath, dtype=str, on_bad_lines='skip')

            for idx, row in df.iterrows():
                proj_name = get_col_val(row, 'PROJECT NAME', 'NAME')
                if not proj_name:
                    continue

                proj_dict = row.to_dict()

                state_num = get_col_val(row, 'STATE PROJECT NUMBER', 'STATE PROJECT NO', 'STATE PROJ NUM')
                prog_num = get_col_val(row, 'PROGRAM NUMBER', 'PROGRAM NO', 'PROGRAM NUM')
                proj_type = get_col_val(row, 'PROJECT TYPE', 'TYPE')
                fed_num = get_col_val(row, 'FEDERAL PROJECT NUMBER', 'FEDERAL PROJ NUM')
                raw_award = get_col_val(row, 'AWARD')
                raw_supp = get_col_val(row, 'SUPPLEMENTALS', 'SUPPLEMENTAL')
                raw_pct = get_col_val(row, 'PROJECT COMPLETION PERCENTAGE', 'COMPLETION PERCENTAGE', 'PERCENTAGE', '% COMPLETE')
                raw_complete_flag = get_col_val(row, 'PROJECT COMPLETE?', 'COMPLETE?', 'COMPLETED')
                
                raw_pm = get_col_val(row, 'PROJECT MANAGER', 'PM', 'MANAGER')
                assigned_pm = normalize_pm_name(raw_pm, pm_tag)

                award_clean = clean_currency(raw_award)
                supp_clean = clean_currency(raw_supp)
                total_val_clean = award_clean + supp_clean

                clean_pct = clean_completion_pct(raw_pct)
                proj_dict['PROJECT COMPLETION PERCENTAGE'] = clean_pct

                if not state_num or state_num.lower() in ['nan', 'null', 'n/a', 'none', '']:
                    clean_num = f"PROJ-{pm_tag.upper()}-{idx+1}"
                else:
                    clean_num = re.sub(r'\s+', '', state_num)

                is_pct_100 = (clean_pct == "100%")
                is_flag_yes = raw_complete_flag.lower() in ['yes', 'y', 'complete', 'completed', 'true']
                is_completed_sheet = (pm_tag == 'Completed')

                is_completed_final = is_completed_sheet or is_pct_100 or is_flag_yes

                clean_prog_num = sanitize_fin_proj(prog_num)
                fmis_status = match_fmis_program_level(program_map, prog_num, fed_num)

                proj_dict['AWARD_CLEAN'] = award_clean
                proj_dict['SUPPLEMENTAL_CLEAN'] = supp_clean
                proj_dict['TOTAL_VALUE_CLEAN'] = total_val_clean
                proj_dict['SPENT_DESIGN_CLEAN'] = 0.0
                proj_dict['SPENT_CONST_CLEAN'] = 0.0
                proj_dict['CLEAN_NUM'] = clean_num
                proj_dict['STATE PROJECT NUMBER'] = state_num if state_num else clean_num
                proj_dict['PROGRAM NUMBER'] = prog_num
                proj_dict['PROGRAM_NUM_CLEAN'] = clean_prog_num
                proj_dict['FED_NUM_CLEAN'] = fed_num
                proj_dict['PROJECT TYPE'] = proj_type
                proj_dict['PROJECT_TYPE_CLEAN'] = proj_type
                proj_dict['SOURCE_PM'] = assigned_pm
                proj_dict['ORIGINAL_TAB'] = pm_tag
                proj_dict['IS_COMPLETED'] = is_completed_final
                proj_dict['FMIS_STATUS'] = fmis_status

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