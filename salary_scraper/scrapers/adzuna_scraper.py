"""
Adzuna Salary Scraper v2
========================
- Всі 113 Djinni категорій
- Append mode → один файл adzuna_all.csv росте щодня
- Схема: category_original | category_djinni | experience_original |
         experience_label | salary_min | salary_max | country | scrape_date | source
- Маппінг через category_mapping.csv
"""
 
import os
import time
import logging
import requests
import pandas as pd
from datetime import date, datetime
from pathlib import Path
 
# ── CONFIG ────────────────────────────────────────────────────────
APP_ID  = os.environ.get("ADZUNA_APP_ID",  "6c5ca315")
APP_KEY = os.environ.get("ADZUNA_APP_KEY", "40436f0e9aac9f58ce2ef3feb474626c")
 
COUNTRIES = {
    "PL": "pl",
    "UK": "gb",
    "US": "us",
    "DE": "de",
    "NL": "nl",
}
 
FX_RATES_TO_USD = {
    "PL": 0.255,   # PLN → USD
    "UK": 1.270,   # GBP → USD
    "US": 1.000,
    "DE": 1.130,   # EUR → USD
    "NL": 1.130,
}
 
# Ключові слова в title для визначення грейду
GRADE_KEYWORDS = {
    "Senior": ["senior", "sr.", "sr ", "lead", "principal", "staff", "head of", "architect"],
    "Middle": ["mid ", "mid-", "middle", "intermediate", "ii ", " ii,", "medior", "associate"],
}
 
# experience_label маппінг → Djinni формат (як у Djinni файлі)
EXPERIENCE_LABEL_MAP = {
    "Middle": "2-3 роки",
    "Senior": "5+ років",
}
 
BASE_DIR     = Path(__file__).parent.parent
DATA_DIR     = BASE_DIR / "data"
LOGS_DIR     = BASE_DIR / "logs"
MAPPING_FILE = BASE_DIR / "category_mapping.csv"
OUTPUT_FILE  = DATA_DIR / "adzuna_all.csv"
 
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
 
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOGS_DIR / "adzuna.log"),
    ],
)
log = logging.getLogger(__name__)
 
 
# ── MAPPING ───────────────────────────────────────────────────────
 
def load_mapping() -> pd.DataFrame:
    """Завантажує маппінг Djinni категорій → Adzuna запити."""
    df = pd.read_csv(MAPPING_FILE)
    log.info(f"Mapping loaded: {len(df)} categories")
    return df
 
 
# ── API ───────────────────────────────────────────────────────────
 
def adzuna_search(country_code: str, query: str, page: int = 1) -> list:
    """Повертає список вакансій з salary_min > 0."""
    url = f"https://api.adzuna.com/v1/api/jobs/{country_code}/search/{page}"
    params = {
        "app_id":                 APP_ID,
        "app_key":                APP_KEY,
        "what":                   query,
        "results_per_page":       50,
        "sort_by":                "relevance",
        "salary_include_unknown": 0,
        "content-type":           "application/json",
    }
    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        return r.json().get("results", [])
    except requests.HTTPError as e:
        log.warning(f"HTTP {e.response.status_code} — {country_code} / {query}")
        return []
    except Exception as e:
        log.error(f"Request failed — {country_code} / {query}: {e}")
        return []
 
 
def detect_grade(title: str) -> str | None:
    """Визначає грейд по title. None = не визначено (neutral)."""
    t = title.lower()
    for grade, keywords in GRADE_KEYWORDS.items():
        if any(kw in t for kw in keywords):
            return grade
    return None
 
 
# Мінімальний річний дохід для IT (local currency)
# Нижче цього — hourly/daily rate, не annual salary
MIN_ANNUAL_LOCAL = {
    "PL": 30000,    # PLN/рік мінімум (~$7,650) — нижче це годинна ставка
    "UK": 15000,    # GBP/рік мінімум (~$19k) — нижче це hourly
    "US": 30000,    # USD/рік мінімум
    "DE": 20000,    # EUR/рік мінімум
    "NL": 20000,    # EUR/рік мінімум
}
MAX_ANNUAL_LOCAL = {
    "PL": 600000,   # PLN/рік максимум (~$153k) — вище підозріло
    "UK": 250000,   # GBP/рік максимум
    "US": 500000,   # USD/рік максимум
    "DE": 300000,   # EUR/рік максимум
    "NL": 300000,   # EUR/рік максимум
}
 
def calc_stats(results: list, grade: str, fx: float, country: str = "UK") -> dict | None:
    """
    Фільтрує вакансії по грейду, конвертує annual → monthly USD.
    Відкидає hourly/daily rates (занадто малі значення).
    Повертає {salary_min, salary_max} або None якщо даних немає.
    """
    min_annual = MIN_ANNUAL_LOCAL.get(country, 15000)
    max_annual = MAX_ANNUAL_LOCAL.get(country, 500000)
 
    salaries_min = []
    salaries_max = []
    skipped_rate = 0
 
    for r in results:
        detected = detect_grade(r.get("title", ""))
        if detected != grade and detected is not None:
            continue
 
        # Відкидаємо ESTIMATED зарплати (Adzuna прогноз, не реальна з вакансії)
        if r.get("salary_is_predicted", 0) == 1:
            skipped_rate += 1
            continue
 
        s_min = r.get("salary_min") or 0
        s_max = r.get("salary_max") or 0
 
        if s_min <= 0:
            continue
 
        # Відкидаємо hourly/daily rates
        if s_min < min_annual:
            skipped_rate += 1
            continue
 
        # Відкидаємо аномально великі значення
        if s_min > max_annual:
            skipped_rate += 1
            continue
 
        salaries_min.append(s_min / 12 * fx)
        salaries_max.append((s_max or s_min) / 12 * fx)
 
    if skipped_rate > 0:
        log.debug(f"  Skipped {skipped_rate} hourly/daily rate entries")
 
    MIN_SAMPLE = 5  # мінімум реальних вакансій для довіри результату
    if len(salaries_min) < MIN_SAMPLE:
        log.debug(f"  Too few real salary data points: {len(salaries_min)} < {MIN_SAMPLE}")
        return None
 
    def trimmed_median(vals: list) -> float:
        """
        Trimmed median: відкидаємо top і bottom 15% як outliers,
        потім беремо median решти.
        Захищає від VP/Director вакансій що тягнуть avg вгору.
        """
        if len(vals) <= 2:
            return sorted(vals)[len(vals)//2]
        sorted_vals = sorted(vals)
        cut = max(1, int(len(sorted_vals) * 0.15))
        trimmed = sorted_vals[cut:-cut]
        if not trimmed:
            trimmed = sorted_vals
        mid = len(trimmed) // 2
        if len(trimmed) % 2 == 0:
            return (trimmed[mid-1] + trimmed[mid]) / 2
        return trimmed[mid]
 
    result_min = round(trimmed_median(salaries_min))
    result_max = round(trimmed_median(salaries_max))
 
    return {
        "salary_min": result_min,
        "salary_max": result_max,
        "count":      len(salaries_min),
    }
 
 
# ── DEDUP ─────────────────────────────────────────────────────────
 
def load_existing_keys() -> set:
    """
    Завантажує вже існуючі записи як set ключів
    (category_djinni, experience_label, country, scrape_date)
    для дедублікації при повторному запуску того ж дня.
    """
    if not OUTPUT_FILE.exists():
        return set()
    try:
        df = pd.read_csv(OUTPUT_FILE, usecols=[
            "category_djinni", "experience_label", "country", "scrape_date"
        ])
        keys = set(zip(
            df["category_djinni"],
            df["experience_label"],
            df["country"],
            df["scrape_date"],
        ))
        log.info(f"Existing records: {len(keys)} unique keys in {OUTPUT_FILE.name}")
        return keys
    except Exception as e:
        log.warning(f"Could not load existing keys: {e}")
        return set()
 
 
def append_to_master(rows: list):
    """
    Дозаписує нові рядки в adzuna_all.csv.
    Якщо файл не існує — створює з заголовком.
    Якщо існує — дописує без заголовку (append mode).
    """
    if not rows:
        return
 
    df_new = pd.DataFrame(rows)
    write_header = not OUTPUT_FILE.exists()
 
    df_new.to_csv(
        OUTPUT_FILE,
        mode="a",
        header=write_header,
        index=False,
        encoding="utf-8-sig",
    )
    log.info(f"Appended {len(rows)} rows → {OUTPUT_FILE.name} (total size check below)")
    try:
        total = sum(1 for _ in open(OUTPUT_FILE)) - 1  # мінус header
        log.info(f"Total rows in {OUTPUT_FILE.name}: {total:,}")
    except Exception:
        pass
 
 
# ── MAIN ──────────────────────────────────────────────────────────
 
def run():
    # Якщо передано SCRAPE_COUNTRY — скрапимо тільки її (для паралельних jobs)
    # Якщо не передано — скрапимо всі країни (backward compatible)
    import os
    single_country = os.environ.get("SCRAPE_COUNTRY", "").strip().upper()
    if single_country:
        if single_country not in COUNTRIES:
            log.error(f"Unknown country: {single_country}. Valid: {list(COUNTRIES.keys())}")
            return
        active_countries = {single_country: COUNTRIES[single_country]}
    else:
        active_countries = COUNTRIES
 
    log.info("=" * 65)
    log.info(f"Adzuna scraper v2 started: {datetime.now().isoformat()}")
    log.info(f"Countries: {list(active_countries.keys())}")
    log.info("=" * 65)
 
    mapping    = load_mapping()
    today      = date.today().isoformat()
    existing   = load_existing_keys()
    new_rows   = []
    skipped    = 0
    no_data    = 0
 
    for _, row in mapping.iterrows():
        djinni_cat   = row["djinni_category"]
        adzuna_query = row["adzuna_query"]
 
        for country_key, country_code in active_countries.items():
            fx = FX_RATES_TO_USD.get(country_key, 1.0)
 
            for grade in ["Middle", "Senior"]:
                experience_label = EXPERIENCE_LABEL_MAP[grade]  # "2-3 роки" / "5+ років"
 
                # Перевірка дедублікації — пропускаємо якщо вже є запис на сьогодні
                dedup_key = (djinni_cat, experience_label, country_key, today)
                if dedup_key in existing:
                    skipped += 1
                    continue
 
                # Запит до Adzuna
                results = adzuna_search(country_code, adzuna_query)
                time.sleep(0.4)  # ~250 req/day ліміт
 
                stats = calc_stats(results, grade, fx, country_key)
 
                if not stats:
                    no_data += 1
                    log.debug(f"  No data: {djinni_cat} | {grade} | {country_key}")
                    # Все одно пишемо рядок з null — щоб знати що запит був
                    stats = {"salary_min": None, "salary_max": None, "count": 0}
 
                new_rows.append({
                    "category_original":  adzuna_query,       # як прийшло від Adzuna
                    "category_djinni":    djinni_cat,          # Djinni slug
                    "experience_original": grade,              # "Middle" / "Senior"
                    "experience_label":   experience_label,    # "2-3 роки" / "5+ років"
                    "salary_min":         stats["salary_min"],
                    "salary_max":         stats["salary_max"],
                    "country":            country_key,
                    "scrape_date":        today,
                    "source":             "adzuna",
                })
 
                if stats["salary_min"]:
                    log.info(
                        f"  ✓ {djinni_cat:25s} | {grade:7s} | {country_key} | "
                        f"${stats['salary_min']:,}–${stats['salary_max']:,} "
                        f"(n={stats['count']})"
                    )
 
    # Дозаписуємо в майстер-файл
    append_to_master(new_rows)
 
    log.info("\n── SUMMARY ──────────────────────────────────────────────")
   
