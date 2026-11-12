"""
Builds dashboard_data.js from the CSV files that auto_sync.py downloads.

What this version does (v2, 2026-11-12):
  - Reads the 8 project manager tabs and the Complete tab. The Cancelled and
    CDS tabs are left out on purpose.
  - Keeps only the 20 approved columns.
  - A project is "complete" if it is on the Complete tab, or if
    "Project Complete?" says Yes.
  - A blank completion percentage stays blank ("not entered") instead of 0%.
  - Milestones are read from the milestone date columns, so the chart can
    place each project at the latest milestone it has actually reached.
  - FMIS is matched on state project number (FMIS "Recipient Project #").
  - The map is rebuilt from kml/Master Coordinates.kml on every run.
  - Anything the script cannot read cleanly is listed in "issues", so the
    Data Issues tab can show each manager what to fix in their sheet.
Uses only the Python standard library.
"""
import csv
import html
import json
import os
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date, datetime, timezone

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(PROJECT_DIR, "dashboard_data.js")
KML_FILE = os.path.join(PROJECT_DIR, "kml", "Master Coordinates.kml")
FINANCIAL_FILE = os.path.join(PROJECT_DIR, "Inactive_120PED_Inactive.csv")

# (tab name, file, is this the Complete tab?)
SHEETS_TO_PROCESS = [
    ("Cameron",   "Dashboard_2026_Cameron.csv",   False),
    ("Jennifer",  "Dashboard_2026_Jennifer.csv",  False),
    ("Kyle",      "Dashboard_2026_Kyle.csv",      False),
    ("Kylena",    "Dashboard_2026_Kylena.csv",    False),
    ("Rhonda",    "Dashboard_2026_Rhonda.csv",    False),
    ("Sharonnia", "Dashboard_2026_Sharonnia.csv", False),
    ("Travis",    "Dashboard_2026_Travis.csv",    False),
    ("Brian",     "Dashboard_2026_Brian.csv",     False),
    ("Complete",  "Dashboard_2026_Complete.csv",  True),
]

# The 20 approved columns: output field -> sheet header (spaces and line
# breaks in headers are ignored when matching).
COLUMNS = {
    "name":              "PROJECT NAME",
    "program_number":    "PROGRAM NUMBER",
    "state_number":      "STATE PROJECT NUMBER",
    "federal_number":    "FEDERAL PROJECT NUMBER",
    "project_type":      "PROJECT TYPE",
    "award_year":        "AWARD YEAR",
    "district":          "DISTRICT",
    "county":            "COUNTY",
    "award":             "AWARD",
    "supplementals":     "SUPPLEMENTALS",
    "consultant":        "CONSULTANT",
    "manager":           "PROJECT MANAGER",
    "design_ntp":        "DESIGN NOTICE TO PROCEED",
    "plans_30":          "30% PLANS RECEIVED",
    "plans_90":          "90% PLANS RECEIVED",
    "nepa":              "NEPA COMPLETE",
    "pse":               "PS&E SUBMITTED",
    "pct_complete":      "PROJECT COMPLETION PERCENTAGE",
    "complete_flag":     "PROJECT COMPLETE?",
    "status_update":     "STATUS UPDATE",
}

# Milestones in order. The chart places a project at the last one reached.
MILESTONES = [
    ("design_ntp", "Design NTP"),
    ("plans_30",   "30% Plans"),
    ("plans_90",   "90% Plans"),
    ("nepa",       "NEPA Complete"),
    ("pse",        "PS&E Submitted"),
]

KNOWN_PROJECT_TYPES = {"TA", "RT", "SFRTP", "FBD"}

# Last names and other spellings used in the PROJECT MANAGER column.
MANAGER_NAMES = {
    "cameron": "Cameron", "cameron hunt": "Cameron", "hunt": "Cameron",
    "jennifer": "Jennifer", "jennifer ballard": "Jennifer", "ballard": "Jennifer",
    "kyle": "Kyle", "kyle oliver": "Kyle", "oliver": "Kyle",
    "kylena": "Kylena", "kylena nunnally": "Kylena", "nunnally": "Kylena",
    "rhonda": "Rhonda", "rhonda brisendine": "Rhonda", "brisendine": "Rhonda",
    "sharonnia": "Sharonnia", "sharonnia osayaba": "Sharonnia", "osayaba": "Sharonnia",
    "travis": "Travis", "travis hayes": "Travis", "hayes": "Travis",
    "brian": "Brian", "brian chapman": "Brian", "b. chapman": "Brian", "chapman": "Brian",
    "mark scoular": "Mark Scoular (Retired)", "scoular": "Mark Scoular (Retired)",
    "scott mcclanahan": "Scott McClanahan (Retired)", "mcclanahan": "Scott McClanahan (Retired)",
}

NOT_APPLICABLE = {"n/a", "na", "not applicable"}
NOT_YET = {"", "-", "tba", "tbd", "n", "no", "pending"}
YES_WORDS = {"y", "yes", "complete", "completed", "done", "true"}


# ---------------------------------------------------------------- helpers

def norm_header(h):
  return re.sub(r"\s+", "", str(h)).upper()


def clean_text(v):
  """Trims spaces (including non-breaking spaces) and joins multi-line cells."""
  v = str(v or "").replace("\xa0", " ")
  lines = [" ".join(line.split()) for line in v.splitlines()]
  return " / ".join(line for line in lines if line)


def key_of(v):
  """Letters and digits only, upper case. Used to match numbers across sheets."""
  return re.sub(r"[^A-Za-z0-9]", "", str(v or "")).upper()


def split_numbers(v):
  """A cell can hold several state project numbers on separate lines."""
  parts = re.split(r"[\n;,]+|\s{2,}", str(v or "").replace("\xa0", " "))
  return [key_of(p) for p in parts if key_of(p)]


def parse_money(raw):
  """Returns (amount or None, note or None)."""
  text = str(raw or "").strip()
  if not text or text.lower() in NOT_APPLICABLE or text == "-":
    return None, None
  amounts = re.findall(r"\$?\s*([\d,]+(?:\.\d+)?)", text)
  if not amounts:
    return None, f'could not read "{clean_text(text)}" as a dollar amount'
  note = None
  values = []
  for a in amounts:
    if "," in a and not re.fullmatch(r"\d{1,3}(,\d{3})*(\.\d+)?", a):
      note = f'"{clean_text(text)}" looks mistyped (commas in the wrong place); read as ${float(a.replace(",", "")):,.2f}'
    values.append(float(a.replace(",", "")))
  if len(values) > 1:
    note = (f'{len(values)} amounts in one cell ("{clean_text(text)}"); '
            f"the dashboard adds them to ${sum(values):,.2f}")
  return sum(values), note


def parse_percent(raw):
  """Returns (percent 0-100 or None, note or None)."""
  text = clean_text(raw)
  low = text.lower()
  if not text or low in NOT_APPLICABLE or low in NOT_YET:
    return None, None
  if re.search(r"\d{1,4}/\d{1,2}(/\d{1,4})?", text):
    return None, f'"{text}" is a date, not a percentage'
  m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
  if m:
    return min(100.0, float(m.group(1))), None
  m = re.fullmatch(r"(\d+(?:\.\d+)?)", text)
  if m:
    num = float(m.group(1))
    if "." in text and num <= 1:      # 0.95 typed as a fraction
      num *= 100
    return min(100.0, num), None
  return None, f'could not read "{text}" as a percentage'


DATE_PATTERNS = [
    (r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", "mdy"),
    (r"\b(\d{1,2})/(\d{1,2})/(\d{2})\b", "mdy2"),
    (r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", "ymd"),
    (r"\b(\d{1,2})/(\d{4})\b", "my"),
]


def find_dates(text):
  found = []
  taken = []
  for pattern, kind in DATE_PATTERNS:
    for m in re.finditer(pattern, text):
      if any(s <= m.start() < e for s, e in taken):
        continue
      try:
        g = [int(x) for x in m.groups()]
        if kind == "mdy":
          d = date(g[2], g[0], g[1])
        elif kind == "mdy2":
          d = date(2000 + g[2], g[0], g[1])
        elif kind == "ymd":
          d = date(g[0], g[1], g[2])
        else:
          d = date(g[1], g[0], 1)
      except ValueError:
        continue
      taken.append((m.start(), m.end()))
      found.append((d, text[m.end():m.end() + 3]))
  return found


def parse_milestone(raw):
  """
  Returns a dict: state is one of
    done      - has a date or a Yes
    planned   - only an estimated date ("E" after it)
    skipped   - N/A, this milestone does not apply
    not_yet   - blank, TBA, No
    unclear   - text the script cannot read (a name, a typo)
  """
  text = clean_text(raw)
  low = text.lower()
  if low in NOT_APPLICABLE or re.fullmatch(r"(pce|ndpce)\s*-?\s*na", low):
    return {"state": "skipped", "date": None, "text": text}
  if low in NOT_YET:
    return {"state": "not_yet", "date": None, "text": text}
  if low in YES_WORDS:
    return {"state": "done", "date": None, "text": text}
  dates = find_dates(text)
  if dates:
    actual = [d for d, after in dates if not re.match(r"\s*E\b", after)]
    if actual:
      return {"state": "done", "date": max(actual).isoformat(), "text": text}
    return {"state": "planned", "date": max(d for d, _ in dates).isoformat(), "text": text}
  if re.fullmatch(r"(19|20)\d\d", text):
    return {"state": "done", "date": f"{text}-01-01", "text": text}
  return {"state": "unclear", "date": None, "text": text}


def parse_years(raw):
  return sorted({int(y) for y in re.findall(r"\b(?:19|20)\d\d\b", str(raw or ""))})


def parse_district(raw):
  text = clean_text(raw)
  m = re.search(r"(\d{1,2})", text)
  if m and 1 <= int(m.group(1)) <= 10:
    return f"District {int(m.group(1))}"
  return None


def manager_name(raw, tab, is_complete_tab):
  text = clean_text(raw)
  if text:
    return MANAGER_NAMES.get(text.lower(), text), text.lower() in MANAGER_NAMES
  return ("Not listed" if is_complete_tab else tab), True


# ------------------------------------------------------------ source files

def read_tab(path):
  """Returns (header list, rows as dicts keyed by normalized header, notes)."""
  with open(path, encoding="utf-8-sig", newline="") as f:
    rows = list(csv.reader(f))
  if not rows:
    return [], [], []
  header = [norm_header(h) for h in rows[0]]
  notes = []
  # Sharonnia's tab: Award Year values sit in column A with no header.
  wanted = norm_header(COLUMNS["award_year"])
  if wanted not in header and header and header[0] == "":
    first = [r[0].strip() for r in rows[1:] if r and r[0].strip()]
    if first and sum(bool(re.fullmatch(r"(19|20)\d\d", v)) for v in first) >= 0.8 * len(first):
      header[0] = wanted
      notes.append("Column A has no header but holds award years. The dashboard reads it as "
                   "Award Year; please type AWARD YEAR in that header cell.")
  out = []
  for i, r in enumerate(rows[1:], start=2):   # sheet row numbers start at 2
    rec = {"_row": i}
    for h, v in zip(header, r):
      if h and h not in rec:
        rec[h] = v
    rec["_any"] = any(c.strip() for c in r)
    out.append(rec)
  return header, out, notes


def load_fmis():
  """FMIS rows keyed by state project number (Recipient Project #)."""
  by_number = defaultdict(list)
  if not os.path.exists(FINANCIAL_FILE):
    print("  [!] FMIS file missing; every project will show 'Not on inactive list'.")
    return by_number, False
  with open(FINANCIAL_FILE, encoding="utf-8-sig", newline="") as f:
    rows = list(csv.reader(f))
  head_i = next((i for i, r in enumerate(rows[:10])
                 if "INACTIVEY/N" in [norm_header(c) for c in r]), None)
  if head_i is None:
    print("  [!] FMIS file has no 'Inactive Y/N' column; skipping FMIS.")
    return by_number, False
  header = [norm_header(c) for c in rows[head_i]]
  col = {h: i for i, h in enumerate(header)}

  def get(r, name):
    i = col.get(norm_header(name))
    return r[i].strip() if i is not None and i < len(r) else ""

  for r in rows[head_i + 1:]:
    number = key_of(get(r, "Recipient Project #"))
    if not number or not get(r, "Project #"):
      continue
    by_number[number].append({
        "fmis_project": get(r, "Project #"),
        "title": get(r, "Project Title"),
        "inactive": get(r, "Inactive Y/N").upper() == "Y",
        "obligated": parse_money(get(r, "Obligated Amount"))[0],
        "expended": parse_money(get(r, "Amount Expended"))[0],
        "unexpended": parse_money(get(r, "Unexpended Balance"))[0],
        "ped": get(r, "PED (FMIS)"),
        "phase": get(r, "Phase"),
        "notes": get(r, "Notes"),
    })
  print(f"  [OK] FMIS: {sum(len(v) for v in by_number.values())} rows, "
        f"{len(by_number)} state project numbers")
  return by_number, True


def load_map():
  """Reads the KML file into GeoJSON line features."""
  features = []
  if not os.path.exists(KML_FILE):
    print("  [!] KML file missing; the map will be empty.")
    return features
  ns = {"k": "http://www.opengis.net/kml/2.2"}
  root = ET.parse(KML_FILE).getroot()
  for pm in root.iter("{http://www.opengis.net/kml/2.2}Placemark"):
    name = (pm.findtext("k:name", "", ns) or "").strip()
    desc_html = pm.findtext("k:description", "", ns) or ""
    desc = clean_text(html.unescape(re.sub(r"<[^>]+>", "\n", desc_html)))
    lines = []
    for ls in pm.iter("{http://www.opengis.net/kml/2.2}LineString"):
      coords = []
      for pt in (ls.findtext("k:coordinates", "", ns) or "").split():
        parts = pt.split(",")
        if len(parts) >= 2:
          coords.append([round(float(parts[0]), 6), round(float(parts[1]), 6)])
      if len(coords) >= 2:
        lines.append(coords)
    points = []
    for p in pm.iter("{http://www.opengis.net/kml/2.2}Point"):
      parts = (p.findtext("k:coordinates", "", ns) or "").strip().split(",")
      if len(parts) >= 2:
        points.append([round(float(parts[0]), 6), round(float(parts[1]), 6)])
    if lines:
      geometry = ({"type": "LineString", "coordinates": lines[0]} if len(lines) == 1
                  else {"type": "MultiLineString", "coordinates": lines})
    elif points:
      geometry = {"type": "Point", "coordinates": points[0]}
    else:
      continue
    features.append({"type": "Feature", "geometry": geometry,
                     "properties": {"label": name, "key": key_of(name),
                                    "description": desc, "project_ids": []}})
  print(f"  [OK] Map: {len(features)} lines from Master Coordinates.kml")
  return features


# ------------------------------------------------------------------ build

def build():
  print("Building dashboard_data.js...")
  fmis, fmis_loaded = load_fmis()
  features = load_map()
  map_keys = defaultdict(list)
  for f in features:
    map_keys[f["properties"]["key"]].append(f)

  projects, issues, tab_counts = [], [], []

  def issue(p, field, problem, tab=None, row=None, manager=None, name=None):
    issues.append({
        "project_id": p["id"] if p else None,
        "tab": p["tab"] if p else tab,
        "row": p["row"] if p else row,
        "manager": p["manager"] if p else manager,
        "project": p["name"] if p else (name or ""),
        "field": field,
        "problem": problem,
    })

  for tab, filename, is_complete_tab in SHEETS_TO_PROCESS:
    path = os.path.join(PROJECT_DIR, filename)
    if not os.path.exists(path):
      print(f"  [!] Missing file {filename}; skipping the {tab} tab")
      tab_counts.append({"tab": tab, "projects": 0, "missing_file": True})
      continue
    header, rows, notes = read_tab(path)
    for n in notes:
      issue(None, "Award Year", n, tab=tab, row=1, manager=tab)
    missing_cols = [label for label in COLUMNS.values()
                    if norm_header(label) not in header
                    and not (is_complete_tab and label == "DISTRICT")]
    for label in missing_cols:
      issue(None, label.title(), f"The {tab} tab has no {label} column.",
            tab=tab, row=1, manager=tab)

    count = 0
    for rec in rows:
      raw = {k: rec.get(norm_header(label), "") for k, label in COLUMNS.items()}
      name = clean_text(raw["name"])
      if not name:
        if rec["_any"]:
          issue(None, "Project Name", "Row has data but no project name, so it is not shown.",
                tab=tab, row=rec["_row"], manager=tab)
        continue
      count += 1
      mgr, known_mgr = manager_name(raw["manager"], tab, is_complete_tab)
      p = {
          "id": f"{tab}-{rec['_row']}",
          "tab": tab,
          "row": rec["_row"],
          "name": name,
          "program_number": clean_text(raw["program_number"]),
          "state_number": clean_text(raw["state_number"]),
          "federal_number": clean_text(raw["federal_number"]),
          "project_type": clean_text(raw["project_type"]).upper(),
          "award_year": clean_text(raw["award_year"]),
          "award_years": parse_years(raw["award_year"]),
          "district": parse_district(raw["district"]),
          "county": clean_text(raw["county"]),
          "consultant": clean_text(raw["consultant"]),
          "manager": mgr,
          "status_update": str(raw["status_update"] or "").strip(),
          "complete_flag": clean_text(raw["complete_flag"]),
      }

      # Money
      p["award"], note = parse_money(raw["award"])
      if note:
        issue(p, "Award", note)
      elif p["award"] is None:
        issue(p, "Award", "Award amount is blank.")
      p["supplementals"], note = parse_money(raw["supplementals"])
      if note:
        issue(p, "Supplementals", note)
      p["total"] = (p["award"] or 0) + (p["supplementals"] or 0)

      # Completion
      p["pct_complete"], note = parse_percent(raw["pct_complete"])
      if note:
        issue(p, "Completion %", note)
      flag_yes = p["complete_flag"].lower() in YES_WORDS
      p["is_complete"] = is_complete_tab or flag_yes
      if p["pct_complete"] is None and not p["is_complete"]:
        issue(p, "Completion %", "Completion percentage is blank.")
      if p["pct_complete"] == 100 and not p["is_complete"]:
        issue(p, "Project Complete?", 'Shows 100% but "Project Complete?" is not Yes.')
      if is_complete_tab and p["complete_flag"] and not flag_yes:
        issue(p, "Project Complete?", f'On the Complete tab but "Project Complete?" says '
                                      f'"{p["complete_flag"]}".')

      # Milestones
      p["milestones"] = {}
      latest = None
      for key, label in MILESTONES:
        m = parse_milestone(raw[key])
        p["milestones"][key] = m
        if m["state"] == "done":
          latest = key
        elif m["state"] == "unclear":
          issue(p, label, f'"{m["text"]}" is not a date.')
      p["latest_milestone"] = latest

      # Other checks
      if not p["state_number"]:
        issue(p, "State Project Number", "State project number is blank.")
      if not p["award_years"]:
        issue(p, "Award Year", "Award year is blank." if not p["award_year"]
              else f'Could not read "{p["award_year"]}" as a year.')
      if not is_complete_tab and not p["district"]:
        issue(p, "District", "District is blank." if not clean_text(raw["district"])
              else f'Could not read district "{clean_text(raw["district"])}".')
      if p["project_type"] and p["project_type"] not in KNOWN_PROJECT_TYPES:
        issue(p, "Project Type", f'"{p["project_type"]}" is not one of TA, RT, SFRTP or FBD.')
      elif not p["project_type"]:
        issue(p, "Project Type", "Project type is blank.")
      if not known_mgr:
        issue(p, "Project Manager", f'"{p["manager"]}" is not a known manager name.')

      # FMIS (matched on state project number)
      numbers = split_numbers(raw["state_number"])
      matched = [row for n in numbers for row in fmis.get(n, [])]
      if not fmis_loaded:
        p["fmis_status"] = "No FMIS data"
      elif not matched:
        p["fmis_status"] = "Not on inactive list"
      else:
        p["fmis_status"] = "Inactive" if any(r["inactive"] for r in matched) else "On list, active"
      p["fmis"] = matched

      # Map
      p["map_keys"] = [n for n in numbers if n in map_keys]
      for n in p["map_keys"]:
        for f in map_keys[n]:
          f["properties"]["project_ids"].append(p["id"])
      p["on_map"] = bool(p["map_keys"])
      if not p["on_map"] and not p["is_complete"]:
        issue(p, "Map", "Active project has no line on the map (no match in Master Coordinates.kml).")

      projects.append(p)
    tab_counts.append({"tab": tab, "projects": count, "missing_file": False})
    print(f"  [OK] {tab}: {count} projects")

  # Rows that are exact repeats (same name, numbers, award and year on the
  # same tab) are kept but marked, and left out of the totals.
  seen = {}
  for p in projects:
    k = (p["tab"], p["name"].lower(), key_of(p["state_number"]), key_of(p["program_number"]),
         p["award"], p["award_year"])
    if k in seen:
      p["duplicate_of"] = seen[k]["id"]
      issue(p, "Duplicate", f'Same project as sheet row {seen[k]["row"]}; '
                            f"counted once in the totals.")
    else:
      p["duplicate_of"] = None
      seen[k] = p
  # Same state project number on an active tab and the Complete tab: shown as
  # separate projects (decision 2026-11-12), but listed so someone can confirm.
  by_number = defaultdict(list)
  for p in projects:
    if p["duplicate_of"] is None:
      for n in split_numbers(p["state_number"]):
        by_number[n].append(p)
  for n, group in by_number.items():
    tabs = {q["tab"] for q in group}
    if "Complete" in tabs and len(tabs) > 1:
      for q in group:
        if q["tab"] != "Complete":
          issue(q, "Duplicate", "Same state project number is also on the Complete tab. "
                                "Shown as a separate project; please confirm.")

  for f in features:
    f["properties"]["matched"] = bool(f["properties"]["project_ids"])

  counted = [p for p in projects if p["duplicate_of"] is None]
  summary = {
      "projects": len(projects),
      "counted_projects": len(counted),
      "repeat_rows": len(projects) - len(counted),
      "active": sum(not p["is_complete"] for p in counted),
      "complete": sum(p["is_complete"] for p in counted),
      "award_total": round(sum(p["award"] or 0 for p in counted), 2),
      "supplementals_total": round(sum(p["supplementals"] or 0 for p in counted), 2),
      "map_lines": len(features),
      "map_lines_without_project": sum(not f["properties"]["matched"] for f in features),
      "issues": len(issues),
  }
  summary["value_total"] = round(summary["award_total"] + summary["supplementals_total"], 2)

  data = {
      "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
      "milestones": [{"key": k, "label": l} for k, l in MILESTONES],
      "tabs": tab_counts,
      "summary": summary,
      "projects": projects,
      "issues": issues,
      "geojson": {"type": "FeatureCollection", "features": features},
  }
  with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write("// Written by build_dashboard_data.py. Do not edit by hand.\n")
    f.write("const DASHBOARD_DATA = ")
    json.dump(data, f, separators=(",", ":"))
    f.write(";\n")

  print(f"\nDone: {summary['projects']} projects ({summary['active']} active, "
        f"{summary['complete']} complete, {summary['repeat_rows']} repeat rows), "
        f"total value ${summary['value_total']:,.2f}, {summary['issues']} data issues.")


if __name__ == "__main__":
  build()
