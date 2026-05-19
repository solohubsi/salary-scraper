"""
ITJobsWatch Scraper v3 (UK only)
=================================
Ключові зміни vs v2:
- ОДИН URL на категорію (не окремі для senior/middle)
- Middle = 25th percentile зарплат
- Senior = 75th percentile зарплат
- Парсинг виправлено: шукаємо конкретні рядки таблиці
 
ITJobsWatch URL format: /jobs/uk/{slug}.do
Slug використовує пробіли (в URL кодуються як %20 автоматично)
"""
 
import time
import logging
import requests
import pandas as pd
from datetime import date, datetime
from pathlib import Path
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
 
 
def fetch_salary(slug: str) -> dict:
    """
    Парсить сторінку ITJobsWatch для slug.
    Повертає: median, pct25, pct75 (annual GBP).
 
    Middle = 25th percentile (нижня квартиль)
    Senior = 75th percentile (верхня квартиль)
    """
    url = f"https://www.itjobswatch.co.uk/jobs/uk/{slug.replace(chr(32), chr(43))}.do"
 
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        log.warning(f"Fetch failed {url}: {e}")
        return {}
 
    soup   = BeautifulSoup(r.text, "html.parser")
    result = {"median": None, "pct25": None, "pct75": None, "url": url}
 
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
 
        # Fallback якщо немає percentiles
        if result["median"] and not result["pct25"]:
            result["pct25"] = result["median"] * 0.80
        if result["median"] and not result["pct75"]:
            result["pct75"] = result["median"] * 1.25
 
    except Exception as e:
        log.debug(f"Parse error {url}: {e}")
 
    return result
 
 
def to_monthly_usd(annual_gbp: float) -> int:
    return round(annual_gbp / 12 * GBP_TO_USD)
 
 
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
    log.info(f"Appended {len(rows)} rows to {OUTPUT_FILE.name}")
    try:
        total = sum(1 for _ in open(OUTPUT_FILE)) - 1
        log.info(f"Total rows in {OUTPUT_FILE.name}: {total:,}")
    except Exception:
        pass
 
 
def run():
    log.info("=" * 65)
    log.info(f"ITJobsWatch scraper v3 started: {datetime.now().isoformat()}")
    log.info("Middle = 25th percentile | Senior = 75th percentile")
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
            log.debug(f"  Skip {djinni_cat} — no ITJobsWatch slug")
            continue
 
        mid_key = (djinni_cat, "2-3 роки", "UK", today)
        sen_key = (djinni_cat, "5+ років", "UK", today)
        if mid_key in existing and sen_key in existing:
            skipped += 2
            continue
 
        # Один запит на категорію
        data = fetch_salary(slug)
        time.sleep(1.5)
 
        pct25  = data.get("pct25")
        median = data.get("median")
        pct75  = data.get("pct75")
 
        if not any([median, pct25, pct75]):
            no_data += 1
            log.debug(f"  No data: {djinni_cat} | {slug}")
            for grade in ["Middle", "Senior"]:
                new_rows.append({
                    "category_original":   slug,
                    "category_djinni":     djinni_cat,
                    "experience_original": grade,
                    "experience_label":    EXPERIENCE_LABEL_MAP[grade],
                    "salary_min":          None,
                    "salary_max":          None,
                    "country":             "UK",
                    "scrape_date":         today,
                    "source":              "itjobswatch",
                })
            continue
 
        # Middle = навколо 25th percentile
        if pct25:
            mid_min = to_monthly_usd(pct25 * 0.90)
            mid_max = to_monthly_usd(pct25 * 1.10)
        elif median:
            mid_min = to_monthly_usd(median * 0.75)
            mid_max = to_monthly_usd(median * 0.90)
        else:
            mid_min = mid_max = None
 
        # Senior = навколо 75th percentile
        if pct75:
            sen_min = to_monthly_usd(pct75 * 0.90)
            sen_max = to_monthly_usd(pct75 * 1.10)
        elif median:
            sen_min = to_monthly_usd(median * 1.10)
            sen_max = to_monthly_usd(median * 1.30)
        else:
            sen_min = sen_max = None
 
        for grade, s_min, s_max in [("Middle", mid_min, mid_max), ("Senior", sen_min, sen_max)]:
            new_rows.append({
                "category_original":   slug,
                "category_djinni":     djinni_cat,
                "experience_original": grade,
                "experience_label":    EXPERIENCE_LABEL_MAP[grade],
                "salary_min":          s_min,
                "salary_max":          s_max,
                "country":             "UK",
                "scrape_date":         today,
                "source":              "itjobswatch",
            })
 
        if mid_min:
            log.info(
                f"  OK {djinni_cat:25s} | "
                f"Mid ${mid_min:,}-${mid_max:,} | "
                f"Sen ${sen_min:,}-${sen_max:,} | "
                f"(25p=£{pct25 or 0:,.0f} med=£{median or 0:,.0f} 75p=£{pct75 or 0:,.0f})"
            )
 
    append_to_master(new_rows)
 
    log.info("\n-- SUMMARY --")
    log.info(f"  Categories: {len(new_rows)//2} | With data: {len([r for r in new_rows if r['salary_min']])//2} | No data: {no_data} | Skipped: {skipped//2}")
    log.info(f"  Output: {OUTPUT_FILE}")
 
 
if __name__ == "__main__":
    run()
