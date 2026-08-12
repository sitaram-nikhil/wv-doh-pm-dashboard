import os
import re
import json
import zipfile
import xml.etree.ElementTree as ET
import pandas as pd

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
KML_DIR = os.path.join(PROJECT_DIR, 'kml')

def clean_proj_num(val):
    if pd.isna(val):
        return ""
    return re.sub(r'\s+', '', str(val)).upper()

def clean_currency(series):
    cleaned = (
        series.astype(str)
              .str.replace('$', '', regex=False)
              .str.replace(',', '', regex=False)
              .str.replace('(', '-', regex=False)
              .str.replace(')', '', regex=False)
              .str.strip()
    )
    return pd.to_numeric(cleaned, errors='coerce').fillna(0.0)

def find_column(df, target_names):
    # 1. Exact match check
    for target in target_names:
        for col in df.columns:
            if str(col).strip().upper() == target.upper():
                return col
    # 2. Partial match fallback
    for target in target_names:
        for col in df.columns:
            if target.upper() in str(col).strip().upper():
                return col
    return None

def extract_coordinates(coords_text):
    """Converts raw KML coordinate string into GeoJSON coordinate array [[lng, lat], ...]"""
    coords_list = []
    if not coords_text:
        return coords_list
    for token in coords_text.strip().split():
        parts = token.split(',')
        if len(parts) >= 2:
            try:
                lng = float(parts[0])
                lat = float(parts[1])
                coords_list.append([lng, lat])
            except ValueError:
                continue
    return coords_list

def parse_kml_file(filepath):
    """Extracts GeoJSON features from a .kml or .kmz file using robust XML parsing."""
    features = []
    
    try:
        if filepath.endswith('.kmz'):
            with zipfile.ZipFile(filepath, 'r') as z:
                kml_filename = [f for f in z.namelist() if f.endswith('.kml')][0]
                content = z.read(kml_filename)
        else:
            with open(filepath, 'rb') as f:
                content = f.read()
        
        # Strip default XML namespaces for simplified element matching
        xml_str = re.sub(r'xmlns="[^"]+"', '', content.decode('utf-8', errors='ignore'))
        root = ET.fromstring(xml_str)
    except Exception as e:
        print(f"Warning: Could not parse KML/KMZ {os.path.basename(filepath)}: {e}")
        return features

    # Find all Placemark elements anywhere in the tree
    for placemark in root.findall('.//Placemark'):
        name_elem = placemark.find('name')
        raw_name = name_elem.text.strip() if (name_elem is not None and name_elem.text) else "Unnamed Feature"
        
        clean_num = clean_proj_num(raw_name)
        clean_name_str = re.sub(r'[^A-Za-z0-9]', '', raw_name).upper()

        # Find any coordinate elements inside Polygon, LineString, or Point (including MultiGeometry)
        polygons = placemark.findall('.//Polygon/outerBoundaryIs/LinearRing/coordinates')
        lines = placemark.findall('.//LineString/coordinates')
        points = placemark.findall('.//Point/coordinates')

        for poly in polygons:
            coords = extract_coordinates(poly.text)
            if coords:
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [coords]},
                    "properties": {"name": raw_name, "clean_num": clean_num, "clean_name": clean_name_str}
                })

        for line in lines:
            coords = extract_coordinates(line.text)
            if coords:
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": coords},
                    "properties": {"name": raw_name, "clean_num": clean_num, "clean_name": clean_name_str}
                })

        for pt in points:
            coords = extract_coordinates(pt.text)
            if coords:
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": coords[0]},
                    "properties": {"name": raw_name, "clean_num": clean_num, "clean_name": clean_name_str}
                })

    return features

def load_all_kml_features():
    all_features = []
    if not os.path.exists(KML_DIR):
        os.makedirs(KML_DIR, exist_ok=True)
        return all_features

    for file in os.listdir(KML_DIR):
        if file.endswith('.kml') or file.endswith('.kmz'):
            path = os.path.join(KML_DIR, file)
            extracted = parse_kml_file(path)
            all_features.extend(extracted)

    return all_features

def build_data():
    pm_files = {
        'Cameron': 'Dashboard_2026_Cameron.csv',
        'Jennifer': 'Dashboard_2026_Jennifer.csv',
        'Kyle': 'Dashboard_2026_Kyle.csv',
        'Kylena': 'Dashboard_2026_Kylena.csv',
        'Rhonda': 'Dashboard_2026_Rhonda.csv',
        'Sharonnia': 'Dashboard_2026_Sharonnia.csv',
        'Travis': 'Dashboard_2026_Travis.csv',
        'Completed': 'Dashboard_2026_Complete.csv',
        'Cancelled': 'Dashboard_2026_Cancelled_Reallocated.csv'
    }

    all_records = []

    for pm_name, filename in pm_files.items():
        filepath = os.path.join(PROJECT_DIR, filename)
        if os.path.exists(filepath):
            try:
                df = pd.read_csv(filepath)
                if df.empty:
                    continue
                df.columns = [" ".join(str(c).split()) for c in df.columns]

                # Exact column matches with fallback
                state_num_col = find_column(df, ['STATE PROJECT NUMBER'])
                fed_num_col = find_column(df, ['FEDERAL PROJECT NUMBER'])
                prog_num_col = find_column(df, ['PROGRAM NUMBER', 'PROGRAM #'])
                proj_type_col = find_column(df, ['PROJECT TYPE', 'PROGRAM TYPE'])

                award_col = find_column(df, ['AWARD'])
                supp_col = find_column(df, ['SUPPLEMENTALS', 'SUPPLEMENTAL'])
                design_col = find_column(df, ['SPENT (DESIGN)', 'DESIGN SPENT'])
                const_col = find_column(df, ['SPENT (CONSTRUCTION)', 'CONSTRUCTION SPENT'])

                # Clean numeric values
                df['AWARD_CLEAN'] = clean_currency(df[award_col]) if award_col else 0.0
                df['SUPPLEMENTAL_CLEAN'] = clean_currency(df[supp_col]) if supp_col else 0.0
                df['TOTAL_VALUE_CLEAN'] = df['AWARD_CLEAN'] + df['SUPPLEMENTAL_CLEAN']

                df['SPENT_DESIGN_CLEAN'] = clean_currency(df[design_col]) if design_col else 0.0
                df['SPENT_CONST_CLEAN'] = clean_currency(df[const_col]) if const_col else 0.0

                if state_num_col:
                    df['CLEAN_NUM'] = df[state_num_col].apply(clean_proj_num)
                    df = df[df[state_num_col].notna() & (df[state_num_col] != '')]

                # String identifiers
                df['PROGRAM_NUM_CLEAN'] = df[prog_num_col].astype(str).str.strip() if prog_num_col else ""
                df['FED_NUM_CLEAN'] = df[fed_num_col].astype(str).str.strip() if fed_num_col else ""
                df['PROJECT_TYPE_CLEAN'] = df[proj_type_col].astype(str).str.strip().str.upper() if proj_type_col else "UNASSIGNED"

                if not df.empty:
                    df['SOURCE_PM'] = pm_name
                    all_records.append(df)
            except Exception as e:
                print(f"Warning: Could not read {filename}: {e}")

    if not all_records:
        print("[×] Error: No valid CSV records found.")
        return

    master_df = pd.concat(all_records, ignore_index=True)
    master_json = master_df.to_dict(orient='records')

    # Load spatial vector features from kml/ directory
    geojson_features = load_all_kml_features()

    payload = {
        "projects": master_json,
        "geojson": {
            "type": "FeatureCollection",
            "features": geojson_features
        }
    }

    output_js = os.path.join(PROJECT_DIR, 'dashboard_data.js')
    with open(output_js, 'w', encoding='utf-8') as f:
        f.write(f"const DASHBOARD_DATA = {json.dumps(payload, indent=2)};")

    types_found = [t for t in master_df['PROJECT_TYPE_CLEAN'].unique() if t not in ['NAN', 'NULL', 'UNASSIGNED', '']]
    print(f"\n[✓] Dashboard data updated successfully!")
    print(f" - {len(master_json)} total project records compiled across {len(all_records)} tabs")
    print(f" - {len(geojson_features)} map vector shapes loaded from 'kml/' directory")
    print(f" - Detected Program Types: {types_found}")

if __name__ == '__main__':
    build_data()