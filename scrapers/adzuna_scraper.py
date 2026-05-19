"""
Adzuna Salary Scraper
=====================
Аналог Djinni скрапера — збирає salary ranges з Adzuna API
по тих самих 23 IT позиціях для PL, UK, US, DE, NL.

API: https://api.adzuna.com/v1/api
Реєстрація: https://developer.adzuna.com (безкоштовно)
Ліміт: 250 req/day на безкоштовному tier

Структура виводу аналогічна Djinni:
  category | experience_label | salary_min | salary_max | country | scrape_date
"""

import os
import time
import logging
import requests
import pandas as pd
from datetime import date, datetime
from pathlib import Path

# ── CONFIG ────────────────────────────────────────────────────────────
APP_ID  = os.environ.get("ADZUNA_APP_ID",  "6c5ca315")
APP_KEY = os.environ.get("ADZUNA_APP_KEY", "40436f0e9aac9f58ce2ef3feb474626c")

BASE_URL = "https://api.adzuna.com/v1/api/jobs/{country}/histogram"

# Adzuna country codes
COUNTRIES = {
    "PL": "pl",
    "UK": "gb",
    "US": "us",
    "DE": "de",
    "NL": "nl",
}

# Маппінг позицій → пошукові запити Adzuna
# Аналогічно category в Djinni
POSITION_QUERIES = {
    "BE Java":        ["java developer", "java backend developer"],
    "BE Node":        ["node.js developer", "nodejs backend developer"],
    "BE Python":      ["python developer", "python backend developer"],
    "BE Hybris":      ["sap hybris developer", "java developer"],     # fallback→java
    "FS Java":        ["java fullstack developer", "java developer"],
    "FS Node":        ["node.js fullstack developer", "nodejs developer"],
    "FS PHP":         ["php developer", "php fullstack developer"],
    "FS .Net":        [".net developer", "c# developer"],
    "FS Python":      ["python fullstack developer", "python developer"],
    "FE":             ["frontend developer", "react developer"],
    "FE Java":        ["java frontend developer", "java developer"],   # fallback→java
    "FE Platforms":   ["react developer", "frontend developer"],
    "QA":             ["qa engineer", "software tester", "test automation engineer"],
    "DevOps":         ["devops engineer", "cloud engineer", "sre engineer"],
    "PM":             ["project manager", "it project manager"],
    "UI/UX Design":   ["ux designer", "ui ux designer"],
    "Mobile IOS":     ["ios developer", "swift developer"],
    "Mobile Hybrid":  ["react native developer", "mobile developer"],
    "Mobile Native":  ["android developer", "kotlin developer"],
    "Data Scientist": ["data scientist", "machine learning engineer"],
    "Embedded Dev":   ["embedded software engineer", "firmware developer"],
    "Salesforce Dev": ["salesforce developer", "salesforce engineer"],
}

# Грейди — через фільтр заголовку вакансії
# Adzuna не має поля "experience" — використовуємо title keywords
GRADE_FILTERS = {
    "Middle": ["mid", "middle", "intermediate", "2", "3"],   # ключові слова в title
    "Senior": ["senior", "sr.", "sr ", "lead", "principal"],
}

OUTPUT_DIR = Path(__file__).parent.parent / "data"
OUTPUT_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent.parent / "logs" / "adzuna.log"),
    ],
)
log = logging.getLogger(__name__)


# ── API HELPERS ───────────────────────────────────────────────────────

def adzuna_salary_histogram(country_code: str, query: str, page: int = 1) -> dict:
    """
    GET /jobs/{country}/histogram
    Повертає salary histogram по запиту.
    """
    url = BASE_URL.format(country=country_code)
    params = {
        "app_id":         APP_ID,
        "app_key":        APP_KEY,
        "what":           query,
        "content-type":   "application/json",
        "results_per_page": 50,
        "page":           page,
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        log.warning(f"HTTP {e.response.status_code} for {country_code}/{query}")
        return {}
    except Exception as e:
        log.error(f"Request failed {country_code}/{query}: {e}")
        return {}


def adzuna_search(country_code: str, query: str, page: int = 1) -> dict:
    """
    GET /jobs/{country}/search — для отримання реальних вакансій з salary_min/max.
    """
    url = f"https://api.adzuna.com/v1/api/jobs/{country_code}/search/{page}"
    params = {
        "app_id":           APP_ID,
        "app_key":          APP_KEY,
        "what":             query,
        "what_and":         "developer engineer",
        "results_per_page": 50,
        "sort_by":          "salary",
        "salary_include_unknown": 0,
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error(f"Search failed {country_code}/{query}: {e}")
        return {}


def extract_salary_stats(results: list) -> dict:
    """
    З масиву вакансій витягує salary_min/max/avg.
    Аналогічно Djinni: avg = (min + max) / 2
    """
    salaries_min = [r.get("salary_min", 0) for r in results if r.get("salary_min", 0) > 0]
    salaries_max = [r.get("salary_max", 0) for r in results if r.get("salary_max", 0) > 0]

    if not salaries_min:
        return {"salary_min": None, "salary_max": None, "salary_avg": None, "count": 0}

    avg_min = sum(salaries_min) / len(salaries_min)
    avg_max = sum(salaries_max) / len(salaries_max) if salaries_max else avg_min

    return {
        "salary_min":  round(avg_min),
        "salary_max":  round(avg_max),
        "salary_avg":  round((avg_min + avg_max) / 2),
        "count":       len(salaries_min),
    }


def filter_by_grade(results: list, grade: str) -> list:
    """
    Фільтрує вакансії по грейду через title keywords.
    Аналог Djinni experience_label фільтру.
    """
    keywords = GRADE_FILTERS.get(grade, [])
    filtered = []
    for r in results:
        title = (r.get("title") or "").lower()
        if any(kw in title for kw in keywords):
            filtered.append(r)
    return filtered


def annual_to_monthly_usd(annual: float, country: str, fx_rates: dict) -> float:
    """
    Конвертує річну зарплату в місячну USD.
    Adzuna повертає annual salary в локальній валюті.
    """
    monthly_local = annual / 12
    rate = fx_rates.get(country, 1.0)
    return round(monthly_local * rate)


# ── FX RATES ─────────────────────────────────────────────────────────
# Статичні курси — оновлювати вручну або підключити API (exchangerate.host free)
FX_RATES_TO_USD = {
    "PL": 0.255,   # PLN → USD
    "UK": 1.270,   # GBP → USD
    "US": 1.000,   # USD → USD
    "DE": 1.130,   # EUR → USD
    "NL": 1.130,   # EUR → USD
}


# ── MAIN SCRAPER ──────────────────────────────────────────────────────

def scrape_country(country_key: str, country_code: str) -> list:
    """
    Скрапить усі позиції для однієї країни.
    Повертає список рядків аналогічно Djinni output.
    """
    log.info(f"Scraping {country_key} ({country_code})...")
    rows = []
    fx = FX_RATES_TO_USD.get(country_key, 1.0)

    for position, queries in POSITION_QUERIES.items():
        for grade in ["Middle", "Senior"]:
            all_results = []

            # Пробуємо кілька запитів для позиції (беремо перший що дає результати)
            for query in queries:
                data = adzuna_search(country_code, query, page=1)
                results = data.get("results", [])

                if results:
                    grade_results = filter_by_grade(results, grade)
                    if len(grade_results) >= 3:   # мінімум 3 вакансії для довіри
                        all_results = grade_results
                        break
                    elif not all_results:         # зберігаємо навіть малу вибірку як fallback
                        all_results = results

                time.sleep(0.5)   # rate limiting — 250 req/day

            stats = extract_salary_stats(all_results)
            if stats["count"] == 0:
                log.debug(f"  No data: {country_key} | {position} | {grade}")
                continue

            row = {
                "category":         position,
                "experience_label": grade,
                "salary_min":       annual_to_monthly_usd(stats["salary_min"] or 0, country_key, FX_RATES_TO_USD),
                "salary_max":       annual_to_monthly_usd(stats["salary_max"] or 0, country_key, FX_RATES_TO_USD),
                "salary_avg":       annual_to_monthly_usd(stats["salary_avg"] or 0, country_key, FX_RATES_TO_USD),
                "vacancies":        stats["count"],
                "candidates":       0,   # Adzuna не надає кількість кандидатів
                "country":          country_key,
                "scrape_date":      date.today().isoformat(),
                "source":           "adzuna",
            }
            rows.append(row)
            log.info(f"  ✓ {position} {grade}: min=${row['salary_min']} max=${row['salary_max']} (n={stats['count']})")

    return rows


def run():
    """
    Основна функція — запускається кроном або вручну.
    Результат зберігається в data/adzuna_YYYY-MM-DD.csv
    """
    log.info("=" * 60)
    log.info(f"Adzuna scraper started: {datetime.now().isoformat()}")
    log.info("=" * 60)

    all_rows = []

    for country_key, country_code in COUNTRIES.items():
        rows = scrape_country(country_key, country_code)
        all_rows.extend(rows)
        log.info(f"  {country_key}: {len(rows)} rows collected")
        time.sleep(2)   # пауза між країнами

    if not all_rows:
        log.error("No data collected! Check API credentials.")
        return

    df = pd.DataFrame(all_rows)

    # Зберігаємо щоденний файл (аналогічно Djinni)
    today = date.today().isoformat()
    out_path = OUTPUT_DIR / f"adzuna_{today}.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    log.info(f"Saved: {out_path} ({len(df)} rows)")

    # Також оновлюємо зведений файл (latest)
    latest_path = OUTPUT_DIR / "adzuna_latest.csv"
    df.to_csv(latest_path, index=False, encoding="utf-8-sig")
    log.info(f"Updated: {latest_path}")

    # Статистика
    log.info("\n── SUMMARY ──")
    for country in df["country"].unique():
        cnt = len(df[df["country"] == country])
        log.info(f"  {country}: {cnt} position/grade combos")
    log.info(f"Total: {len(df)} rows | Date: {today}")


if __name__ == "__main__":
    run()
