"""
ITJobsWatch Scraper v3 (UK only)
=================================
Ключові зміни vs v2:
- ОДИН URL на категорію (не окремі для senior/middle)
- Middle = 25th percentile зарплат
- Senior = 75th percentile зарплат
- Парсинг виправлено: шукаємо конкретні рядки таблиці

ITJobsWatch URL format: /jobs/uk/{slug}.do
Slug використовує + між словами
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

    def parse_gbp(text: str):
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
                value_text = cells[-1].get_text
