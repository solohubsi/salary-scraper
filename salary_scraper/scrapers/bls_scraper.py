"""
BLS (Bureau of Labor Statistics) Scraper — USA
================================================
Офіційна держстатистика, найнадійніше джерело для US.
API: https://api.bls.gov/publicAPI/v2/timeseries/data/
Без ключа: до 500 req/day | З ключем: до 25,000 req/day

SOC коди IT ролей:
  15-1252 — Software Developers
  15-1211 — Computer Systems Analysts
  15-1244 — Network and Computer Systems Admins (DevOps proxy)
  15-1211 — QA Analysts
  15-1299 — Computer Occupations (catch-all)
  11-3021 — Computer and IT Managers (PM proxy)
  15-1211 — Info Security Analysts

OEWS series format: OEWS{area}{occupation}{datatype}
  area: 000000 = national
  datatype: 03 = median annual, 04 = mean annual, 09 = 10th pct, 12 = 90th pct

Append mode: один файл bls_all.csv росте щодня.
"""

import os
import time
import logging
import requests
import pandas as pd
from datetime import date, datetime
from pathlib import Path

BLS_API_KEY = os.environ.get("BLS_API_KEY", "")  # опційно, без ключа теж працює
BLS_URL     = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

BASE_DIR    = Path(__file__).parent.parent
DATA_DIR    = BASE_DIR / "data"
LOGS_DIR    = BASE_DIR / "logs"
OUTPUT_FILE = DATA_DIR / "bls_all.csv"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOGS_DIR / "bls.log"),
    ],
)
log = logging.getLogger(__name__)

# Рік останніх OEWS даних (виходять щороку в травні)
BLS_DATA_YEAR = "2024"

# ── SOC → Djinni mapping ──────────────────────────────────────────
# OEWS series: OEWS + area(6) + occupation(6) + datatype(2)
# National median annual: OEWS000000{SOC_nodash}03

BLS_SERIES = {
    # djinni_category: {soc_code, series_id_median, series_id_p25, series_id_p75}
    "java":           {"soc": "15-1252", "title": "Software Developers"},
    "python":         {"soc": "15-1252", "title": "Software Developers"},
    "javascript":     {"soc": "15-1252", "title": "Software Developers"},
    "node_js":        {"soc": "15-1252", "title": "Software Developers"},
    "dotnet":         {"soc": "15-1252", "title": "Software Developers"},
    "php":            {"soc": "15-1252", "title": "Software Developers"},
    "react":          {"soc": "15-1252", "title": "Software Developers"},
    "angular":        {"soc": "15-1252", "title": "Software Developers"},
    "vue":            {"soc": "15-1252", "title": "Software Developers"},
    "golang":         {"soc": "15-1252", "title": "Software Developers"},
    "rust":           {"soc": "15-1252", "title": "Software Developers"},
    "scala":          {"soc": "15-1252", "title": "Software Developers"},
    "ruby":           {"soc": "15-1252", "title": "Software Developers"},
    "kotlin":         {"soc": "15-1252", "title": "Software Developers"},
    "swift":          {"soc": "15-1252", "title": "Software Developers"},
    "ios":            {"soc": "15-1257", "title": "Web Developers and Digital Designers"},
    "android":        {"soc": "15-1252", "title": "Software Developers"},
    "react_native":   {"soc": "15-1252", "title": "Software Developers"},
    "flutter":        {"soc": "15-1252", "title": "Software Developers"},
    "fullstack":      {"soc": "15-1252", "title": "Software Developers"},
    "qa":             {"soc": "15-1253", "title": "Software Quality Assurance"},
    "qa_automation":  {"soc": "15-1253", "title": "Software Quality Assurance"},
    "qa_manual":      {"soc": "15-1253", "title": "Software Quality Assurance"},
    "dev_ops":        {"soc": "15-1244", "title": "Network and Computer Systems"},
    "embedded":       {"soc": "17-2061", "title": "Computer Hardware Engineers"},
    "data_science":   {"soc": "15-2051", "title": "Data Scientists"},
    "data_analyst":   {"soc": "15-2041", "title": "Statisticians/Data Analysts"},
    "data_engineer":  {"soc": "15-1243", "title": "Database Architects"},
    "ml_ai":          {"soc": "15-2051", "title": "Data Scientists"},
    "project_manager":{"soc": "11-3021", "title": "Computer and IT Managers"},
    "product_manager":{"soc": "11-3021", "title": "Computer and IT Managers"},
    "product_owner":  {"soc": "11-3021", "title": "Computer and IT Managers"},
    "delivery_manager":{"soc":"11-3021", "title": "Computer and IT Managers"},
    "engineering_manager":{"soc":"11-3021","title":"Computer and IT Managers"},
    "business_analyst":{"soc":"15-1211","title":"Computer Systems Analysts"},
    "salesforce":     {"soc": "15-1252", "title": "Software Developers"},
    "sap":            {"soc": "15-1252", "title": "Software Developers"},
    "ui_ux":          {"soc": "15-1255", "title": "Web and Digital Interface Designers"},
    "security":       {"soc": "15-1212", "title": "Information Security Analysts"},
    "security_analyst":{"soc":"15-1212","title":"Information Security Analysts"},
    "information_security":{"soc":"15-1212","title":"Info Security Analysts"},
    "penetration_tester":{"soc":"15-1212","title":"Info Security Analysts"},
    "sysadmin":       {"soc": "15-1244", "title": "Network/Systems Administrators"},
    "sql_dba":        {"soc": "15-1243", "title": "Database Architects"},
    "erp_systems":    {"soc": "15-1252", "title": "Software Developers"},
    "asp_net":        {"soc": "15-1252", "title": "Software Developers"},
    "dotnet_cloud":   {"soc": "15-1252", "title": "Software Developers"},
    "dotnet_web":     {"soc": "15-1257", "title": "Web Developers"},
    "magento":        {"soc": "15-1257", "title": "Web Developers"},
    "wordpress":      {"soc": "15-1257", "title": "Web Developers"},
    "drupal":         {"soc": "15-1257", "title": "Web Developers"},
    "laravel":        {"soc": "15-1252", "title": "Software Developers"},
    "symfony":        {"soc": "15-1252", "title": "Software Developers"},
    "yii":            {"soc": "15-1252", "title": "Software Developers"},
    "unity":          {"soc": "15-1252", "title": "Software Developers"},
    "game_developer": {"soc": "15-1252", "title": "Software Developers"},
    "gamedev":        {"soc": "15-1252", "title": "Software Developers"},
    "game_design":    {"soc": "27-1014", "title": "Multimedia Artists/Animators"},
    "design":         {"soc": "27-1024", "title": "Graphic Designers"},
    "graphic_design": {"soc": "27-1024", "title": "Graphic Designers"},
    "ui_ux":          {"soc": "15-1255", "title": "Web/Digital Interface Designers"},
    "ux_research":    {"soc": "15-1255", "title": "Web/Digital Interface Designers"},
    "product_design": {"soc": "15-1255", "title": "Web/Digital Interface Designers"},
    "content_design": {"soc": "27-3043", "title": "Writers and Authors"},
    "content_manager":{"soc": "27-3043", "title": "Writers and Authors"},
    "recruiter":      {"soc": "13-1071", "title": "Human Resources Specialists"},
    "scrum_master":   {"soc": "11-3021", "title": "Computer and IT Managers"},
    "lead":           {"soc": "15-1252", "title": "Software Developers"},
    "head_chief":     {"soc": "11-3021", "title": "Computer and IT Managers"},
    "cto":            {"soc": "11-1021", "title": "General and Operations Managers"},
    "cpo":            {"soc": "11-1021", "title": "General and Operations Managers"},
    "ceo":            {"soc": "11-1011", "title": "Chief Executives"},
}

# Percentile multipliers для Middle/Senior (BLS дає тільки медіану)
# Middle ~= median * 0.85 (25th-50th pct)
# Senior ~= median * 1.25 (75th-90th pct)
GRADE_MULTIPLIERS = {
    "Middle": {"min_mult": 0.75, "max_mult": 0.95},
    "Senior": {"min_mult": 1.10, "max_mult": 1.45},
}

EXPERIENCE_LABEL_MAP = {
    "Middle": "2-3 роки",
    "Senior": "5+ років",
}


def build_series_id(soc: str) -> dict:
    """Будує OEWS series IDs для медіани, 25th і 75th percentile."""
    soc_clean = soc.replace("-", "")
    return {
        "median": f"OEWS000000{soc_clean}03",   # median annual
        "p25":    f"OEWS000000{soc_clean}09",   # 10th pct (closest to 25th available)
        "p75":    f"OEWS000000{soc_clean}12",   # 90th pct (for range)
        "mean":   f"OEWS000000{soc_clean}04",   # mean annual
    }


def fetch_bls_series(series_ids: list) -> dict:
    """
    Запит до BLS API. Повертає {series_id: annual_value}.
    """
    payload = {
        "seriesid":  series_ids,
        "startyear": BLS_DATA_YEAR,
        "endyear":   BLS_DATA_YEAR,
    }
    if BLS_API_KEY:
        payload["registrationkey"] = BLS_API_KEY

    try:
        r = requests.post(BLS_URL, json=payload, timeout=20)
        r.raise_for_status()
        data = r.json()

        results = {}
        for series in data.get("Results", {}).get("series", []):
            sid  = series["seriesID"]
            vals = series.get("data", [])
            if vals:
                # Беремо найсвіжіше значення
                latest = sorted(vals, key=lambda x: x.get("year", "0"), reverse=True)[0]
                raw    = latest.get("value", "").replace(",", "")
                if raw and raw != "-":
                    try:
                        results[sid] = float(raw)
                    except ValueError:
                        pass
        return results

    except Exception as e:
        log.error(f"BLS API error: {e}")
        return {}


def annual_to_monthly(annual: float) -> int:
    return round(annual / 12)


def load_existing_keys() -> set:
    if not OUTPUT_FILE.exists():
        return set()
    try:
        df = pd.read_csv(OUTPUT_FILE, usecols=[
            "category_djinni", "experience_label", "country", "scrape_date"
        ])
        return set(zip(df["category_djinni"], df["experience_label"],
                       df["country"], df["scrape_date"]))
    except Exception:
        return set()


def append_to_master(rows: list):
    if not rows:
        return
    df_new = pd.DataFrame(rows)
    write_header = not OUTPUT_FILE.exists()
    df_new.to_csv(OUTPUT_FILE, mode="a", header=write_header,
                  index=False, encoding="utf-8-sig")
    log.info(f"Appended {len(rows)} rows → {OUTPUT_FILE.name}")


def run():
    log.info("=" * 65)
    log.info(f"BLS scraper started: {datetime.now().isoformat()}")
    log.info(f"Data year: {BLS_DATA_YEAR}")
    log.info("=" * 65)

    today    = date.today().isoformat()
    existing = load_existing_keys()
    new_rows = []

    # Збираємо унікальні SOC коди (BLS повертає по SOC, а не по Djinni категорії)
    soc_to_categories = {}
    for djinni_cat, info in BLS_SERIES.items():
        soc = info["soc"]
        if soc not in soc_to_categories:
            soc_to_categories[soc] = []
        soc_to_categories[soc].append(djinni_cat)

    # Кешуємо BLS дані по SOC (щоб не робити зайві запити)
    soc_cache = {}
    unique_socs = list(set(info["soc"] for info in BLS_SERIES.values()))

    log.info(f"Fetching BLS data for {len(unique_socs)} unique SOC codes...")

    # BLS приймає до 50 series за раз
    # Батчами по 25 серій (median + mean = 2 на SOC)
    BATCH_SIZE = 25
    all_series_ids = []
    for soc in unique_socs:
        ids = build_series_id(soc)
        all_series_ids.extend([ids["median"], ids["mean"]])

    # Дедублікуємо
    all_series_ids = list(dict.fromkeys(all_series_ids))

    fetched = {}
    for i in range(0, len(all_series_ids), BATCH_SIZE):
        batch = all_series_ids[i:i+BATCH_SIZE]
        result = fetch_bls_series(batch)
        fetched.update(result)
        log.info(f"  BLS batch {i//BATCH_SIZE+1}: {len(result)}/{len(batch)} series returned")
        time.sleep(0.5)

    log.info(f"BLS data fetched: {len(fetched)} series with data")

    # Будуємо рядки для кожної Djinni категорії
    for djinni_cat, info in BLS_SERIES.items():
        soc   = info["soc"]
        title = info["title"]
        ids   = build_series_id(soc)

        median_annual = fetched.get(ids["median"])
        mean_annual   = fetched.get(ids["mean"])

        # Використовуємо median, якщо немає — mean
        base_annual = median_annual or mean_annual
        if not base_annual:
            log.debug(f"  No BLS data: {djinni_cat} (SOC {soc})")
            continue

        for grade in ["Middle", "Senior"]:
            experience_label = EXPERIENCE_LABEL_MAP[grade]
            dedup_key = (djinni_cat, experience_label, "US", today)
            if dedup_key in existing:
                continue

            mult = GRADE_MULTIPLIERS[grade]
            salary_min = annual_to_monthly(base_annual * mult["min_mult"])
            salary_max = annual_to_monthly(base_annual * mult["max_mult"])

            new_rows.append({
                "category_original":   f"BLS SOC {soc} — {title}",
                "category_djinni":     djinni_cat,
                "experience_original": grade,
                "experience_label":    experience_label,
                "salary_min":          salary_min,
                "salary_max":          salary_max,
                "country":             "US",
                "scrape_date":         today,
                "source":              "bls",
            })

            log.info(
                f"  ✓ {djinni_cat:25s} | {grade:7s} | US | "
                f"${salary_min:,}–${salary_max:,}  (BLS {BLS_DATA_YEAR} "
                f"median=${annual_to_monthly(base_annual):,}/mo)"
            )

    append_to_master(new_rows)

    log.info("\n── SUMMARY ──────────────────────────────────────────────")
    log.info(f"  Rows written: {len(new_rows)}")
    log.info(f"  Output:       {OUTPUT_FILE}")
    log.info("─" * 65)


if __name__ == "__main__":
    run()
