"""
Salary Data Aggregator
======================
Зводить дані з усіх скраперів в єдину структуру:
  - Djinni (UA) — вже є в системі
  - Adzuna (PL, UK, US, DE, NL)
  - ITJobsWatch (UK, більш точний за Adzuna для UK)

Вихід: merged_salaries_YYYY-MM-DD.csv
Формат: аналогічний Djinni output для безшовної інтеграції в Power BI.
"""

import pandas as pd
import logging
from pathlib import Path
from datetime import date

DATA_DIR  = Path(__file__).parent.parent / "data"
LOG_DIR   = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# Для UK — ITJobsWatch пріоритетніше за Adzuna (медіани з реальних вакансій)
# Для решти — Adzuna
UK_SOURCE_PRIORITY = "itjobswatch"


def load_latest(pattern: str) -> pd.DataFrame:
    """Завантажує найсвіжіший файл за паттерном."""
    files = sorted(DATA_DIR.glob(pattern))
    if not files:
        log.warning(f"No files matching {pattern}")
        return pd.DataFrame()
    latest = files[-1]
    log.info(f"Loading: {latest.name}")
    return pd.read_csv(latest, encoding="utf-8-sig")


def normalize(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """
    Нормалізує DataFrame до єдиної схеми:
    category | experience_label | salary_min | salary_max | salary_avg | country | source | scrape_date
    """
    if df.empty:
        return df

    # Стандартизуємо колонки
    rename_map = {
        "category":         "category",
        "experience_label": "experience_label",
        "salary_min":       "salary_min",
        "salary_max":       "salary_max",
        "salary_avg":       "salary_avg",
        "salary_median":    "salary_avg",   # ITJobsWatch використовує median як avg
        "country":          "country",
        "scrape_date":      "scrape_date",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    # Заповнюємо відсутні колонки
    if "salary_avg" not in df.columns:
        df["salary_avg"] = ((df.get("salary_min", 0) + df.get("salary_max", 0)) / 2).round()

    df["source"] = source

    return df[[
        "category", "experience_label",
        "salary_min", "salary_max", "salary_avg",
        "country", "source", "scrape_date"
    ]].copy()


def merge_uk_sources(adzuna_uk: pd.DataFrame, itjobswatch: pd.DataFrame) -> pd.DataFrame:
    """
    Для UK — бере ITJobsWatch де є дані, Adzuna як fallback.
    """
    if itjobswatch.empty:
        return adzuna_uk

    itjw_keys = set(zip(itjobswatch["category"], itjobswatch["experience_label"]))

    if adzuna_uk.empty:
        return itjobswatch

    # Adzuna UK — тільки ті позиції, де немає ITJobsWatch
    adzuna_fallback = adzuna_uk[
        ~adzuna_uk.apply(lambda r: (r["category"], r["experience_label"]) in itjw_keys, axis=1)
    ]

    merged = pd.concat([itjobswatch, adzuna_fallback], ignore_index=True)
    log.info(f"UK merged: {len(itjobswatch)} ITJobsWatch + {len(adzuna_fallback)} Adzuna fallback")
    return merged


def run(djinni_path: str = None):
    """
    Основна функція агрегації.
    djinni_path: шлях до Djinni CSV якщо не стандартний.
    """
    today = date.today().isoformat()
    log.info(f"Aggregating salary data for {today}")

    dfs = []

    # ── 1. Djinni (UA) ────────────────────────────────────────────
    if djinni_path:
        djinni = pd.read_csv(djinni_path, encoding="utf-8-sig")
    else:
        djinni = load_latest("djinni_*.csv")

    if not djinni.empty:
        # Djinni має свою схему — адаптуємо
        djinni["country"] = "UA"
        djinni["source"]  = "djinni"
        # Вибираємо лише Middle (2-3 роки) та Senior (5+ років)
        djinni = djinni[djinni["experience_label"].isin(["2-3 роки", "5+ років"])].copy()
        djinni["experience_label"] = djinni["experience_label"].map({
            "2-3 роки": "Middle",
            "5+ років": "Senior",
        })
        djinni = normalize(djinni, "djinni")
        dfs.append(djinni)
        log.info(f"Djinni (UA): {len(djinni)} rows")

    # ── 2. Adzuna (PL, UK, US, DE, NL) ───────────────────────────
    adzuna = load_latest("adzuna_*.csv")
    if not adzuna.empty:
        adzuna_norm = normalize(adzuna, "adzuna")

        adzuna_uk   = adzuna_norm[adzuna_norm["country"] == "UK"]
        adzuna_rest = adzuna_norm[adzuna_norm["country"] != "UK"]

        dfs.append(adzuna_rest)
        log.info(f"Adzuna (non-UK): {len(adzuna_rest)} rows")
    else:
        adzuna_uk = pd.DataFrame()

    # ── 3. ITJobsWatch (UK) ───────────────────────────────────────
    itjobswatch = load_latest("itjobswatch_*.csv")
    if not itjobswatch.empty:
        itjw_norm = normalize(itjobswatch, "itjobswatch")
        uk_merged = merge_uk_sources(adzuna_uk, itjw_norm)
        dfs.append(uk_merged)
    elif not adzuna_uk.empty:
        dfs.append(adzuna_uk)
        log.info(f"UK (Adzuna only): {len(adzuna_uk)} rows")

    # ── Merge all ─────────────────────────────────────────────────
    if not dfs:
        log.error("No data sources available!")
        return

    final = pd.concat(dfs, ignore_index=True)
    final = final.dropna(subset=["salary_avg"])
    final = final[final["salary_avg"] > 0]

    # Сортуємо аналогічно до Djinni output
    final = final.sort_values(["country", "category", "experience_label"]).reset_index(drop=True)

    out_path = DATA_DIR / f"merged_salaries_{today}.csv"
    final.to_csv(out_path, index=False, encoding="utf-8-sig")
    log.info(f"\nSaved: {out_path} ({len(final)} total rows)")

    # Summary
    log.info("\n── SUMMARY ──")
    summary = final.groupby(["country", "source"]).size().reset_index(name="rows")
    for _, row in summary.iterrows():
        log.info(f"  {row['country']:4s} | {row['source']:15s}: {row['rows']} rows")

    # Pivot для quick review
    pivot = final.pivot_table(
        values="salary_avg",
        index=["category", "experience_label"],
        columns="country",
        aggfunc="mean"
    ).round(0)

    pivot_path = DATA_DIR / f"salary_pivot_{today}.csv"
    pivot.to_csv(pivot_path, encoding="utf-8-sig")
    log.info(f"Pivot saved: {pivot_path}")

    return final


if __name__ == "__main__":
    run()
