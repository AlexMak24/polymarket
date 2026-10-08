# trader-analyzer — анализатор weather-кошельков Polymarket

Смотрит чужие кошельки: парсит живые weather-маркеты, определяет стратегию
(лестница / value / specialist / longshot / certain) и выдаёт рекомендации.

**Изолировано от бота.** Не трогает `strategies/weather/`, `telegram-bot/`.

## Запуск

```bash
cd ~/projects/polymarket/trader-analyzer
PYTHON=/Users/alexander/agents-env/bin/python3

$PYTHON cli.py parse "Will the highest temperature in London be 20°C or below on August 19?"
$PYTHON cli.py status
$PYTHON cli.py report
$PYTHON cli.py report --json
$PYTHON cli.py recommend --hours 48
$PYTHON cli.py add 0x... --name WeatherHk
$PYTHON cli.py collect          # KNOWN_WALLETS → profiles.db
$PYTHON cli.py reclassify       # переклассифицировать все профили (сеть)
$PYTHON cli.py discover         # живые лидерборды + трейдеры сегодняшних рынков
$PYTHON cli.py harvest --prune   # только погодные с живых рынков
$PYTHON cli.py refresh --pnl-only            # обновить PnL по всей базе
$PYTHON cli.py refresh --harvest --stale-hours 24   # добор + метрики устаревших
$PYTHON cli.py query --playbook --min-pnl 1000 --min-month 15 --strategy ladder,value
$PYTHON cli.py query --city "Hong Kong" --min-conc 0.5 --sort trades_30d
$PYTHON cli.py strategies        # ранг рабочих стратегий по PnL
$PYTHON cli.py signals          # daily_signals.md
```

Прокси (нужен из РФ): `POLYMARKET_HTTP_PROXY` в `.env` (см. `.env.example`).

Обновление раз в сутки (crontab):

```
0 6 * * * cd ~/projects/polymarket/trader-analyzer && /Users/alexander/agents-env/bin/python3 cli.py refresh --harvest --prune --stale-hours 20 >> refresh.log 2>&1
```

Тесты:

```bash
$PYTHON -m pytest test_city_parser.py test_classifier.py -q
```

## Что умеет парсер

Живые заголовки Polymarket, не только старый `be 27°C on DATE`:

| Формат | Пример |
|--------|--------|
| точный бакет | `Will the highest temperature in London be 22°C on August 19?` |
| край | `20°C or below` / `30°C or higher` |
| °F | `80°F`, `80 °F` |
| событие + outcome | title `Highest temperature in London on August 19` + outcome `21°C` |
| старый NYC | `Will NYC reach 80°F on March 22?` |

## Стратегии

- **ladder** — ≥3 соседних бакетов одного города+даты+типа
- **certain** — доля входов > 85¢
- **longshot** — доля входов < 10¢
- **specialist** — город-специалист (концентрация ≥55%)
- **value** — медиана входа 25–50¢
- **momentum** — медиана 50–70¢
- **mixed / unknown**

`recommend` по умолчанию берёт сделки за последние 48ч (`SIGNAL_RECENCY_HOURS`).

## Модули

| Файл | Что делает |
|------|------------|
| `cli.py` | единая точка входа |
| `city_parser.py` | город / тип / градус / край / дата |
| `classifier.py` | стратегия по сделкам |
| `collector.py` | SQLite `profiles.db` |
| `recommend.py` | корзины для бота |
| `signals.py` | утренняя сводка |
| `api.py` | Polymarket Data API |
| `config.py` | прокси, пороги, пути |
