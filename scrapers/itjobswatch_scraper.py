"""
ITJobsWatch Scraper (UK)
========================
Збирає медіанні зарплати з itjobswatch.co.uk для UK ринку.
URL pattern: https://www.itjobswatch.co.uk/jobs/uk/{skill}.do

Дані: медіана, 25/75 percentile, кількість вакансій.
Оновлення на сайті: щоденне.
Обмеження: тільки UK ринок.

Без API ключа — HTTP scraping публічних сторінок.
"""

import time
import logging
import requests
import pandas as pd
from datetime import date, datetime
from pathlib import Path
from bs4 import BeautifulSoup

OUTPUT_DIR = Path(__file__).parent.parent / "data"
OUTPUT_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent.parent / "logs" / "itjobswatch.log"),
    ],
)
log = logging.getLogger(__name__)

BASE_URL = "https://www.itjobswatch.co.uk/jobs/uk/{skill}.do"
GBP_TO_USD = 1.27  # оновлювати вручну або через fx API

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

# Маппінг позицій → URL slugs для ITJobsWatch
# Перевірено вручну: ці slugs дають результати на сайті
POSITION_SLUGS = {
    "BE Java":         [("senior+java+developer", "Senior"), ("java+developer",        "Middle")],
    "BE Node":         [("senior+node.js+developer","Senior"),("node.js+developer",    "Middle")],
    "BE Python":       [("senior+python+developer","Senior"), ("python+developer",      "Middle")],
    "BE Hybris":       [("senior+java+developer",  "Senior"), ("java+developer",        "Middle")],  # proxy
    "FS Java":         [("senior+java+developer",  "Senior"), ("java+developer",        "Middle")],
    "FS Node":         [("senior+node.js+developer","Senior"),("node.js+developer",    "Middle")],
    "FS PHP":          [("senior+php+developer",   "Senior"), ("php+developer",         "Middle")],
    "FS .Net":         [("senior+.net+developer",  "Senior"), (".net+developer",        "Middle")],
    "FS Python":       [("senior+python+developer","Senior"), ("python+developer",      "Middle")],
    "FE":              [("senior+front+end+developer","Senior"),("front+end+developer","Middle")],
    "FE Java":         [("senior+java+developer",  "Senior"), ("java+developer",        "Middle")],  # proxy
    "FE Platforms":    [("senior+react+developer", "Senior"), ("react+developer",       "Middle")],
    "QA":              [("senior+test+engineer",   "Senior"), ("test+engineer",         "Middle")],
    "DevOps":          [("senior+devops+engineer", "Senior"), ("devops+engineer",       "Middle")],
    "PM":              [("senior+project+manager", "Senior"), ("it+project+manager",    "Middle")],
    "UI/UX Design":    [("senior+ux+designer",     "Senior"), ("ux+designer",           "Middle")],
    "Mobile IOS":      [("senior+ios+developer",   "Senior"), ("ios+developer",         "Middle")],
    "Mobile Hybrid":   [("senior+react+native",    "Senior"), ("react+native+developer","Middle")],
    "Mobile Native":   [("senior+android+developer","Senior"),("android+developer",    "Middle")],
    "Data Scientist":  [("senior+data+scientist",  "Senior"), ("data+scientist",        "Middle")],
    "Embedded Dev":    [("senior+embedded+engineer","Senior"),("embedded+software",    "Middle")],
    "Salesforce Dev":  [("senior+salesforce+developer","Senior"),("salesforce+developer","Middle")],
}


def fetch_itjobswatch(slug: str) -> dict:
    """
    Завантажує сторінку ITJobsWatch і парсить salary stats.
    Повертає: median, pct25, pct75, vacancies (annual GBP).
    """
    url = BASE_URL.format(skill=slug)
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except requests.HTTPError as e:
        log.warning(f"HTTP {e.response.status_code}: {url}")
        return {}
    except Exception as e:
        log.error(f"Request failed {url}: {e}")
        return {}

    soup = BeautifulSoup(r.text, "html.parser")

    result = {
        "url":       url,
        "median":    None,
        "pct25":     None,
        "pct75":     None,
        "vacancies": None,
    }

    # ITJobsWatch: salary stats є в таблиці з class "salary-stats" або inline
    # Шукаємо "Median Salary" → значення поряд
    try:
        # Основна таблиця зарплат
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all(["td", "th"])
                if len(cells) >= 2:
                    label = cells[0].get_text(strip=True).lower()
                    value_text = cells[1].get_text(strip=True).replace(",", "").replace("£", "").replace("$", "")

                    if "median" in label and "salary" in label:
                        try:
                            result["median"] = float(value_text.split()[0])
                        except (ValueError, IndexError):
                            pass

                    elif "25th" in label or "lower quartile" in label:
                        try:
                            result["pct25"] = float(value_text.split()[0])
                        except (ValueError, IndexError):
                            pass

                    elif "75th" in label or "upper quartile" in label:
                        try:
                            result["pct75"] = float(value_text.split()[0])
                        except (ValueError, IndexError):
                            pass

                    elif "vacancies" in label and "ranked" in label:
                        try:
                            result["vacancies"] = int(value_text.split()[0])
                        except (ValueError, IndexError):
                            pass

        # Fallback: шукаємо salary в meta або структурованих даних
        if result["median"] is None:
            # Спроба знайти через span з класом
            for span in soup.find_all(["span", "strong", "td"]):
                text = span.get_text(strip=True)
                if "£" in text and "," in text:
                    clean = text.replace("£", "").replace(",", "").strip()
                    try:
                        val = float(clean.split()[0])
                        if 20000 < val < 250000:  # розумний діапазон для UK IT
                            if result["median"] is None:
                                result["median"] = val
                    except (ValueError, IndexError):
                        pass

    except Exception as e:
        log.debug(f"Parse error {url}: {e}")

    return result


def annual_gbp_to_monthly_usd(annual_gbp: float) -> int:
    """Конвертує annual GBP → monthly USD"""
    return round(annual_gbp / 12 * GBP_TO_USD)


def run():
    """
    Запускається кроном або вручну.
    Результат: data/itjobswatch_YYYY-MM-DD.csv
    """
    log.info("=" * 60)
    log.info(f"ITJobsWatch scraper started: {datetime.now().isoformat()}")
    log.info("=" * 60)

    rows = []

    for position, slug_grade_pairs in POSITION_SLUGS.items():
        for slug, grade in slug_grade_pairs:
            data = fetch_itjobswatch(slug)
            time.sleep(1.5)  # поважаємо сайт

            median    = data.get("median")
            pct25     = data.get("pct25")
            pct75     = data.get("pct75")
            vacancies = data.get("vacancies", 0)

            if median is None:
                log.warning(f"  No data: {position} | {grade} | slug={slug}")
                # Використовуємо midpoint між pct25/pct75 якщо є
                if pct25 and pct75:
                    median = (pct25 + pct75) / 2
                    log.info(f"  Fallback to pct midpoint: {median:.0f}")
                else:
                    continue

            salary_min_usd = annual_gbp_to_monthly_usd(pct25 or median * 0.85)
            salary_max_usd = annual_gbp_to_monthly_usd(pct75 or median * 1.15)
            salary_med_usd = annual_gbp_to_monthly_usd(median)

            row = {
                "category":         position,
                "experience_label": grade,
                "salary_min":       salary_min_usd,
                "salary_max":       salary_max_usd,
                "salary_median":    salary_med_usd,
                "salary_avg":       round((salary_min_usd + salary_max_usd) / 2),
                "vacancies":        vacancies or 0,
                "country":          "UK",
                "scrape_date":      date.today().isoformat(),
                "source":           "itjobswatch",
                "source_url":       data.get("url", ""),
            }
            rows.append(row)
            log.info(
                f"  ✓ {position} {grade}: "
                f"med=${salary_med_usd} "
                f"(£{median:,.0f}/yr | pct25-75: £{pct25 or 0:,.0f}-£{pct75 or 0:,.0f})"
            )

    if not rows:
        log.error("No data collected! Site structure may have changed.")
        return

    df = pd.DataFrame(rows)

    today = date.today().isoformat()
    out_path = OUTPUT_DIR / f"itjobswatch_{today}.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    log.info(f"Saved: {out_path} ({len(df)} rows)")

    latest_path = OUTPUT_DIR / "itjobswatch_latest.csv"
    df.to_csv(latest_path, index=False, encoding="utf-8-sig")

    log.info(f"\nTotal: {len(df)} rows | Middle: {len(df[df['experience_label']=='Middle'])} | Senior: {len(df[df['experience_label']=='Senior'])}")


if __name__ == "__main__":
    run()
