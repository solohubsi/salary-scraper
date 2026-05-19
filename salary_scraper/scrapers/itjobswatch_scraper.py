"""
ITJobsWatch Scraper v2 (UK only)
=================================
- Всі 113 Djinni категорій → пошук на ITJobsWatch
- Append mode → один файл itjobswatch_all.csv росте щодня
- Схема: category_original | category_djinni | experience_original |
         experience_label | salary_min | salary_max | country | scrape_date | source
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
BASE_URL   = "https://www.itjobswatch.co.uk/jobs/uk/{slug}.do"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

# Префікси грейду для ITJobsWatch slug
GRADE_PREFIXES = {
    "Senior": "senior+",
    "Middle": "",   # без префіксу — загальний запит
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


# ── SCRAPER ───────────────────────────────────────────────────────

def fetch_salary(slug: str) -> dict:
    """
    Парсить сторінку ITJobsWatch для slug.
    Повертає: median, pct25, pct75 (annual GBP).
    """
    url = BASE_URL.format(slug=slug)
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        log.warning(f"Fetch failed {url}: {e}")
        return {}

    soup   = BeautifulSoup(r.text, "html.parser")
    result = {"median": None, "pct25": None, "pct75": None, "vacancies": None}

    try:
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if len(cells) < 2:
                    continue
                label = cells[0].get_text(strip=True).lower()
                raw   = cells[1].get_text(strip=True).replace(",", "").replace("£", "").strip()
                val   = None
                try:
                    val = float(raw.split()[0]) if raw else None
                except (ValueError, IndexError):
                    pass

                if val and "median" in label and "salary" in label:
                    result["median"] = val
                elif val and ("25th" in label or "lower quartile" in label):
                    result["pct25"] = val
                elif val and ("75th" in label or "upper quartile" in label):
                    result["pct75"] = val
                elif val and "vacancies" in label and "ranked" in label:
                    result["vacancies"] = int(val)

    except Exception as e:
        log.debug(f"Parse error {url}: {e}")

    return result


def salary_to_monthly_usd(annual_gbp: float) -> int:
    return round(annual_gbp / 12 * GBP_TO_USD)


# ── DEDUP ─────────────────────────────────────────────────────────

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


# ── MAIN ──────────────────────────────────────────────────────────

def run():
    log.info("=" * 65)
    log.info(f"ITJobsWatch scraper v2 started: {datetime.now().isoformat()}")
    log.info("=" * 65)

    mapping  = pd.read_csv(MAPPING_FILE)
    today    = date.today().isoformat()
    existing = load_existing_keys()
    new_rows = []
    skipped  = 0
    no_data  = 0

    for _, row in mapping.iterrows():
        djinni_cat  = row["djinni_category"]
        base_slug   = row["itjobswatch_slug"]

        for grade in ["Middle", "Senior"]:
            experience_label = EXPERIENCE_LABEL_MAP[grade]

            dedup_key = (djinni_cat, experience_label, "UK", today)
            if dedup_key in existing:
                skipped += 1
                continue

            # Senior → "senior+{slug}", Middle → "{slug}"
            slug = GRADE_PREFIXES[grade] + base_slug
            data = fetch_salary(slug)
            time.sleep(1.5)

            median = data.get("median")
            pct25  = data.get("pct25")
            pct75  = data.get("pct75")

            if median is None and pct25 and pct75:
                median = (pct25 + pct75) / 2

            if median is None:
                no_data += 1
                salary_min = None
                salary_max = None
            else:
                salary_min = salary_to_monthly_usd(pct25 or median * 0.85)
                salary_max = salary_to_monthly_usd(pct75 or median * 1.15)

            category_original = (GRADE_PREFIXES[grade] + base_slug).replace("+", " ").strip()

            new_rows.append({
                "category_original":   category_original,
                "category_djinni":     djinni_cat,
                "experience_original": grade,
                "experience_label":    experience_label,
                "salary_min":          salary_min,
                "salary_max":          salary_max,
                "country":             "UK",
                "scrape_date":         today,
                "source":              "itjobswatch",
            })

            if salary_min:
                log.info(
                    f"  ✓ {djinni_cat:25s} | {grade:7s} | UK | "
                    f"${salary_min:,}–${salary_max:,}"
                )
            else:
                log.debug(f"  No data: {djinni_cat} | {grade}")

    append_to_master(new_rows)

    log.info("\n── SUMMARY ──────────────────────────────────────────────")
    log.info(f"  New rows written:  {len([r for r in new_rows if r['salary_min']])}")
    log.info(f"  Null (no data):    {no_data}")
    log.info(f"  Skipped (dedup):   {skipped}")
    log.info(f"  Output file:       {OUTPUT_FILE}")
    log.info("─" * 65)


if __name__ == "__main__":
    run()
