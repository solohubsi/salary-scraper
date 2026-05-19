# Salary Scraper — IT Labor Market Data Collection

Аналог Djinni скрапера (testprHR1) для збору зарплатних даних по 9 країнах.

## Джерела

| Скрапер | Країни | Тип | API ключ |
|---|---|---|---|
| `djinni_scraper` | UA | Вже є в системі | ні (internal) |
| `adzuna_scraper` | PL, UK, US, DE, NL | REST API | потрібен (безкоштовно) |
| `itjobswatch_scraper` | UK | HTTP scraping | ні |

## Структура

```
salary_scraper/
├── scrapers/
│   ├── adzuna_scraper.py        # Adzuna API — 5 країн
│   ├── itjobswatch_scraper.py   # UK медіани з ITJobsWatch
│   └── aggregator.py            # Зводить всі джерела в єдиний CSV
├── data/                        # Вихідні CSV файли
├── logs/                        # Логи запусків
├── .github/workflows/
│   └── salary_scraper.yml       # Cron: щодня о 07:00 UTC
├── requirements.txt
└── README.md
```

## Швидкий старт

### 1. Реєстрація Adzuna API (5 хвилин)
1. Зайти на https://developer.adzuna.com
2. Зареєструватися → отримати `app_id` і `app_key`
3. Безкоштовний tier: 250 req/day

### 2. Додати секрети в GitHub
```
Settings → Secrets → New repository secret:
  ADZUNA_APP_ID  = ваш app_id
  ADZUNA_APP_KEY = ваш app_key
```

### 3. Локальний запуск
```bash
pip install -r requirements.txt

# Adzuna
ADZUNA_APP_ID=xxx ADZUNA_APP_KEY=yyy python scrapers/adzuna_scraper.py

# ITJobsWatch (без ключа)
python scrapers/itjobswatch_scraper.py

# Агрегація
python scrapers/aggregator.py
```

## Вихідні файли

| Файл | Опис |
|---|---|
| `data/adzuna_YYYY-MM-DD.csv` | Adzuna по всіх країнах |
| `data/itjobswatch_YYYY-MM-DD.csv` | UK медіани |
| `data/merged_salaries_YYYY-MM-DD.csv` | Зведений (всі джерела) |
| `data/salary_pivot_YYYY-MM-DD.csv` | Pivot: позиція × країна |

## Схема merged CSV (сумісна з Djinni output)

```
category | experience_label | salary_min | salary_max | salary_avg | country | source | scrape_date
```

## Cron розклад

Файл: `.github/workflows/salary_scraper.yml`
- Щодня о **07:00 UTC** (09:00 Kyiv)
- Ручний запуск: Actions → Run workflow

## Інтеграція з Power BI

Підключити `data/merged_salaries_latest.csv` як data source.
Схема ідентична Djinni — фільтр `experience_label IN ('Middle','Senior')`.
