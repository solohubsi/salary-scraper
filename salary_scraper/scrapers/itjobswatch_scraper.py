"""
ITJobsWatch Scraper v4 (UK only)
=================================
URL format: spaces encoded as %20 (NOT +)
  Middle: /jobs/uk/java%20developer.do       (загальна сторінка)
  Senior: /jobs/uk/senior%20java%20developer.do (senior-specific)
 
Дані: median, 25th/75th percentile (annual GBP)
"""
 
import time
import logging
import requests
import pandas as pd
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote
from bs4 import BeautifulSoup
 
BASE_DIR     = Path(__file__).parent.parent
DATA_DIR     = BASE_DIR / "data"
LOGS_DIR     = BASE_DIR / "logs"
MAPPING_FILE = BASE_DIR / "category_mapping.csv"
OUTPUT_FILE  = DATA_DIR / "itjobswatch_all.csv"
 
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
 
GBP_TO_USD = 1.27
 
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}
 
EXPERIENCE_LABEL_MAP = {
    "Middle": "2-3 роки",
    "Senior": "5+ років",
}
 
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOGS_DIR / "itjobswatch.log"),
    ],
)
log = logging.getLogger(__name__)
 
 
def build_url(slug, grade):
    """
    Будує правильний URL для ITJobsWatch.
    Middle: /jobs/uk/{slug}.do
    Senior: /jobs/uk/senior {slug}.do
    Пробіли кодуються як %20 через quote()
    """
    if grade == "Senior":
        full_slug = "senior " + slug
    else:
        full_slug = slug
    encoded = quote(full_slug)
    return f"https://www.itjobswatch.co.uk/jobs/uk/{encoded}.do"
 
 
def fetch_salary(url):
    """Парсить сторінку ITJobsWatch. Повертає median, pct25, pct75 (annual GBP)."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        log.warning(f"Fetch failed {url}: {e}")
        return {}
 
    soup   = BeautifulSoup(r.text, "html.parser")
    result = {"median": None, "pct25": None, "pct75": None}
 
    def parse_gbp(text):
        cleaned = text.replace("£", "").replace(",", "").strip()
        try:
            val = float(cleaned.split()[0])
            if 15000 < val < 300000:
                return val
        except (ValueError, IndexError):
            pass
        return None
 
    try:
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if len(cells) < 2:
                    continue
                label      = cells[0].get_text(strip=True).lower()
                value_text = cells[-1].get_text(strip=True)
 
                if "median" in label and result["median"] is None:
                    val = parse_gbp(value_text)
                    if val:
                        result["median"] = val
 
                elif ("25th" in label or "lower quartile" in label) and result["pct25"] is None:
                    val = parse_gbp(value_text)
                    if val:
                        result["pct25"] = val
 
                elif ("75th" in label or "upper quartile" in label) and result["pct75"] is None:
                    val = parse_gbp(value_text)
                    if val:
                        result["pct75"] = val
 
        if result["median"] and not result["pct25"]:
            result["pct25"] = result["median"] * 0.80
        if result["median"] and not result["pct75"]:
            result["pct75"] = result["median"] * 1.25
 
    except Exception as e:
        log.debug(f"Parse error {url}: {e}")
 
    return result
 
 
def to_monthly_usd(annual_gbp):
    return round(annual_gbp / 12 * GBP_TO_USD)
 
 
def load_existing_keys():
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
 
 
def append_to_master(rows):
    if not rows:
        return
    df_new = pd.DataFrame(rows)
    write_header = not OUTPUT_FILE.exists()
    df_new.to_csv(OUTPUT_FILE, mode="a", header=write_header,
                  index=False, encoding="utf-8-sig")
    log.info(f"Appended {len(rows)} rows to {OUTPUT_FILE.name}")
    try:
        total = sum(1 for _ in open(OUTPUT_FILE)) - 1
        log.info(f"Total rows in {OUTPUT_FILE.name}: {total:,}")
    except Exception:
        pass
 
 
def run():
    log.info("=" * 65)
    log.info(f"ITJobsWatch scraper v4 started: {datetime.now().isoformat()}")
    log.info("Middle = general page | Senior = senior-specific page")
    log.info("URLs use %20 encoding (not +)")
    log.info("=" * 65)
 
    mapping  = pd.read_csv(MAPPING_FILE)
    today    = date.today().isoformat()
    existing = load_existing_keys()
    new_rows = []
    skipped  = 0
    no_data  = 0
 
    for _, row in mapping.iterrows():
        djinni_cat = row["djinni_category"]
        slug       = str(row.get("itjobswatch_slug", "")).strip()
 
        if not slug or slug == "nan":
            log.debug(f"  Skip {djinni_cat} -- no ITJobsWatch slug")
            continue
 
        for grade in ["Middle", "Senior"]:
            exp_label = EXPERIENCE_LABEL_MAP[grade]
            dedup_key = (djinni_cat, exp_label, "UK", today)
 
            if dedup_key in existing:
                skipped += 1
                continue
 
            url  = build_url(slug, grade)
            data = fetch_salary(url)
            time.sleep(1.5)
 
            median = data.get("median")
            pct25  = data.get("pct25")
            pct75  = data.get("pct75")
 
            if not any([median, pct25, pct75]):
                no_data += 1
                log.debug(f"  No data: {djinni_cat} {grade} | {url}")
                new_rows.append({
                    "category_original":   slug,
                    "category_djinni":     djinni_cat,
                    "experience_original": grade,
                    "experience_label":    exp_label,
                    "salary_min":          None,
                    "salary_max":          None,
                    "country":             "UK",
                    "scrape_date":         today,
                    "source":              "itjobswatch",
                })
                continue
 
            # Middle: навколо медіани або pct25
            # Senior: навколо senior-page медіани або pct75
            if grade == "Senior":
                base = median or pct75
                s_min = to_monthly_usd(base * 0.90) if base else None
                s_max = to_monthly_usd(base * 1.10) if base else None
            else:
                base = median or pct25
                s_min = to_monthly_usd(base * 0.85) if base else None
                s_max = to_monthly_usd(base * 1.00) if base else None
 
            new_rows.append({
                "category_original":   slug,
                "category_djinni":     djinni_cat,
                "experience_original": grade,
                "experience_label":    exp_label,
                "salary_min":          s_min,
                "salary_max":          s_max,
                "country":             "UK",
                "scrape_date":         today,
                "source":              "itjobswatch",
            })
 
            if s_min:
                log.info(
                    f"  OK {djinni_cat:25s} {grade:7s} "
                    f"${s_min:,}-${s_max:,} "
                    f"(med=£{median or 0:,.0f})"
                )
 
    append_to_master(new_rows)
 
    log.info("\n-- SUMMARY --")
    log.info(f"  With data: {len([r for r in new_rows if r['salary_min']])} | No data: {no_data} | Skipped: {skipped}")
    log.info(f"  Output: {OUTPUT_FILE}")
 
 
if __name__ == "__main__":
    run()
