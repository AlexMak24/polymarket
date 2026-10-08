# MVP — Единый парсер+анализатор Polymarket-кошельков (trader-analyzer)

> Стратегия-документ от worker `strategist`. Содержит скоуп, definition of done, kill-критерии и минимальный путь. **Это расширение существующего кода, НЕ перестройка.** Builder: читать целиком, реализовывать по чекпоинтам, не выходить за in-scope.

**Цель:** превратить weather-only анализатор в единый парсер+анализатор кошельков Polymarket, который по адресу кошелька выдаёт «отчёт-портрет» с разбивкой по темам (спорт/политика/крипта/наука/поп-культура/погода), полной историей сделок и on-chain выводами.

**Архитектура (2-3 фразы):** существующий конвейер `api → classifier → collector → cli` остаётся скелетом. В него добавляются два новых слоя — тематический (`topic.py`, уже написан) и on-chain (`onchain.py`, новый) — и снимается погодный фильтр (`weather_ratio` → `topic_distribution`). Ни один модуль не переписывается с нуля.

---

## 1. Текущее состояние (as-is инвентаризация)

| Модуль | Что делает | Статус для MVP |
|---|---|---|
| `api.py` | Data API `/trades` (offset-пагинация, cap `max_trades`), `/positions`, lb-api `fetch_pnl` | **расширить** (full history, on-chain) |
| `city_parser.py` | разбор weather-заголовков (temperature/rain/storm, город/градус/дата) | **не трогать** — становится под-парсером темы `weather` |
| `topic.py` | `classify_topic`/`topic_distribution`/`top_topic`/`topic_ratio` (10 тем) | **есть**, подключить и сузить до 6 |
| `classifier.py` | стратегия кошелька по сделкам (weather-специфично: `weather_ratio`, `detect_ladders` по городам) | **расширить** (topic-aware, убрать weather-gate) |
| `collector.py` | SQLite `profiles.db`, `weather_ratio`-фильтр, `prune_non_weather` | **расширить** (схема v2, topic-поля) |
| `metrics.py` | активность/timestamps (topic-agnostic) | **не трогать** |
| `discover.py` | лидерборды + трейдеры live-рынков (weather-слаги) | **расширить** (все темы) |
| `recommend.py` / `rank_strategies.py` / `signals.py` | корзины / ранг / сводка (weather) | **расширить** (topic-фильтр), необязательно для первого wedge |
| `deep_analyze_unknown.py` | `deep_profile()` — прототип портрета (weather, cap 1000) | **поглотить** в новый `portrait` |
| `dashboard.py` | локальный HTTP-дашборд (weather) | **не трогать** (out-of-scope) |
| `profiles.db` (1.3 MB) | текущие профили | **мигрировать** или пересобрать (см. §9) |

**Тесты:** 42 passed (вкл. 16 тестов `test_topic.py`). План не должен их ломать.

---

## 2. Инварианты — что НЕ трогать (anti-rebuild guardrail)

1. **Не переписывать** `city_parser.py`, `metrics.py`, `api.py` (только аддитивные правки), `dashboard.py`.
2. **Изоляция от бота:** `strategies/weather/`, `telegram-bot/`, `shared/` — не трогать вообще. Только read-only данные.
3. **Read-only по чужим кошелькам:** никаких транзакций, никакой торговли.
4. **Прокси из `.env`** (`POLYMARKET_HTTP_PROXY`) продолжает работать — все новые вызовы идут через `config.make_http_client`.
5. **CLI-контракт:** существующие подкоманды (`parse/status/report/recommend/add/collect/reclassify/discover/ingest/harvest/prune/strategies/signals/query/refresh`) не удаляются; меняется только их семантика (weather → topic). Новый подкоманда `portrait` добавляется.

> Смысл: любое «давайте перепишу collector заново» — нарушение. Изменения точечные и аддитивные.

---

## 3. In-scope MVP (точный список)

1. **Снятие погодного ограничения.** `weather_ratio` и `WEATHER_MIN_RATIO` больше не гейтят сохранение профиля. `prune_non_weather` выпиливается. Профиль сохраняется для любого кошелька с ≥1 BUY.
2. **Тематическая модель — 6 разделов** (см. §5). `topic_distribution` становится главной разбивкой профиля.
3. **Полная история сделок.** Убрать `max_trades`-cap по умолчанию; выкачивать всё, что отдаёт API, с явным окном получения (см. §7).
4. **On-chain выводы.** Новый `onchain.py`: депозиты/выводы USDC+ETH и сверка с lb-api PnL (см. §6).
5. **Отчёт-портрет.** Новый подкоманда `portrait <addr>` → markdown + `--json` (см. §4).
6. **Подключение `topic.py` к конвейеру.** `classify_wallet` и `collector` начинают использовать темы вместо/наряду с погодой.

## 4. Out-of-scope (явно НЕ в MVP)

- Торговля / размещение ордеров / любые мутации на кошельке.
- Реал-тайм / вебсокеты / стриминг.
- ML-ранжирование стратегий (остаётся эвристика `classifier`).
- Кластеризация кошельков / sybil-детект / граф связей.
- UI/дашборд (CLI + markdown/JSON; `dashboard.py` не развиваем).
- Интеграция с Telegram-ботом (`strategies/weather` — отдельный проект).
- Бэктест-движок.
- Другие сети (только Polygon/PolygonScan).
- Скрейпинг решённых рынков для «certain»-скупки.
- Тонкая таксономия (`economics/world/business` как отдельные разделы — см. §5).

---

## 5. Тематическая модель — 6 разделов + other

**Канонические разделы отчёта (ровно 6):**

| Раздел | slug | Источник детекта |
|---|---|---|
| Погода | `weather` | `city_parser` (структурный) + `topic._WEATHER_WORDS` |
| Политика | `politics` | keyword-правило `topic._RULES` |
| Спорт | `sports` | keyword-правило |
| Крипта | `crypto` | keyword-правило |
| Наука | `science` | keyword-правило |
| Поп-культура | `pop_culture` | keyword-правило |

**Решение по существующим лишним темам** (`economics`, `world`, `business`, `other`): в портрете они сворачиваются в единственный бакет `other`. Правила в `topic._RULES` оставляем как внутренние теги (пригодятся post-MVP), но `topic_distribution` для отчёта агрегирует в 6+`other`.

> **Почему keyword, а не Gamma `category`:** Gamma отдаёт `category`/`tags` только на уровне event/market по запросу, а сделки Data API не содержат категорию. Связывать каждую сделку с Gamma-категорией по `conditionId` — дорого и хрупко для MVP. Поэтому: **keyword-классификатор по `title`+`outcome` (уже написан, 16 тестов) — основной; Gamma `category` — опциональный источник дообучения, НЕ обязателен.** (BET-1, §10.)

---

## 6. On-chain выводы (`onchain.py`, новый)

**Что считаем (минимально):**
- Депозиты (входящие USDC/ETH на кошелёк) и выводы (исходящие) — по ERC-20 `Transfer` событиям + нативным `txlist`.
- Нетто-поток (in − out) и текущий баланс USDC/ETH.
- **Сверка:** официальный lb-api PnL vs on-chain нетто (реально ли банкует профит или держит на кошельке).

**Источник (порядок предпочтения):**
1. PolygonScan API — `?module=account&action=tokentx` (USDC) + `action=txlist` (ETH/MATIC). Бесплатный тир, нужен `POLYGONSCAN_API_KEY` в `.env`.
2. Публичный Polygon RPC (`https://polygon-rpc.com`) через `eth_getLogs` — без ключа, но rate-limit.

**Контракты/детали — verify на C1** (не хардкодить вслепую): native USDC `0x3c499c...`, bridged USDC.e `0x2791bc...`, WETH. Точные адреса builder подтверждает одним запросом.

**Kill-переключатель:** если ключа нет И публичный RPC лимитит — секция on-chain отключается, портрет живёт на lb-api PnL (KILL-2, §9).

---

## 7. Полная история сделок

- `api.get_all_trades` меняет сигнатуру: `get_all_trades(wallet, max_trades=None)` → `None` = без cap, пагинация offset до упора.
- Возврат дополняется метаданными: `{"trades": [...], "window": {"from": ts, "to": ts, "count": N, "truncated": bool, "source": "data-api"}}`.
- **Fallback:** если Data API обрезает offset (Goldsky-лимит) — CLOB `clob.polymarket.com/data/trades?user=...` (cursor). Точный лимит и работоспособность CLOB-источника — **ждём результат sage** (см. §11).
- «Полная история» в MVP = «всё, что реально отдаёт API», с **честной** пометкой `truncated` в портрете, а не тихим cap.

---

## 8. Минимальный путь: адрес → портрет (wedge)

**Wedge 0 — «один адрес, всё на месте»** (доказывает вертикаль до флота):

```bash
cd ~/projects/polymarket/trader-analyzer
PYTHON=/Users/alexander/agents-env/bin/python3
$PYTHON cli.py portrait 0x4989bfed5900ba096b08ba1f9b718464527c983e
$PYTHON cli.py portrait 0x4989bfed5900ba096b08ba1f9b718464527c983e --json
```

Внутренний путь `portrait` (ровно эти вызовы, в этом порядке):
1. `full = api.get_all_trades_full(addr)` — вся история + `window` метаданные.
2. `topics = topic.topic_distribution(full["trades"])` — 6+other.
3. `strat = classifier.classify_wallet(full["trades"])` — стратегия (topic-aware).
4. `pnl = api.fetch_pnl(addr)` — официальный PnL.
5. `chain = onchain.flow(addr)` — депозиты/выводы + балансы + нетто (с kill-переключателем).
6. `portrait = merge(...)` → render markdown / JSON.

**Секции портрета (markdown):** `# Portrait <addr>` → идентичность, сводка (PnL, сделки, период), **темы (6 строк + other, с ratio)**, стратегия, on-chain (in/out/нетто/сверка), топ-рынки, `truncated`-флаг.

**Wedge 1 — флот по всем темам:** `collect/discover/ingest/refresh` переключаются с `weather_ratio` на `topic_distribution`; `status/report/query` показывают разбивку по темам; `harvest/prune` удаляют weather-гейт.

**Wedge 2 — агрегация:** `strategies`/`recommend`/`signals` получают `--topic` фильтр (по умолчанию — все темы).

> Порядок wedge'ей — это же и порядок чекпоинтов C0→C6. Builder реализует строго по порядку; каждый wedge оканчивается прохождением своего чекпоинта.

---

## 9. Kill-критерии (триггер → действие)

| # | Триггер | Действие | Кто проверяет |
|---|---|---|---|
| KILL-1 | Data API режет offset < 1000 И CLOB `data/trades` мёртв | «полная история» деградирует до best-effort окна с `truncated=true`; НЕ блокирует остальное | sage подтверждает, builder реализует fallback |
| KILL-2 | Нет `POLYGONSCAN_API_KEY` И публичный RPC лимитит (≥80% ошибок на пробной выборке 5 кошельков) | секция on-chain отключается; портрет = PnL lb-api + темы + история | builder + qa |
| KILL-3 | Accuracy темы < 80% на gold-set из 100 размеченных заголовков (включая спорные «rain» vs «Ukraine») | auto-topic заменяется на «category-only + other» либо topic секция помечается `low_confidence` | builder + reviewer |
| KILL-4 | Миграция `profiles.db` теряет topic-микс (нельзя восстановить темы из хранимых weather-only полей) | пересборка базы с нуля (`collect`+`ingest`), а не lossy-миграция | builder |
| KILL-5 | 2+ из 4 ядер (история/on-chain/темы/портрет) падают по KILL-1..4 | стоп, вернуть `NEEDS_INPUT` оркестратору, НЕ сдавать половинчатый MVP | strategist/orchestrator |

**Правило:** kill отдельной секции ≠ kill MVP. KILL-5 — единственный общий стоп.

---

## 10. Bets (предположения с confidence и verify)

| # | Bet | Confidence | Verify |
|---|---|---|---|
| BET-1 | keyword-классификатор по title/outcome достаточен для 6 тем без Gamma-`category` | high | C3 (gold-set ≥80%) |
| BET-2 | Data API отдаёт полную историю через offset (или CLOB fallback), cap только в `max_trades` нашего кода | medium | **sage результат** + C2 |
| BET-3 | PolygonScan free-key или публичный RPC даёт ERC-20 Transfer для депозитов/выводов без платы | medium | **sage результат** + C4 |
| BET-4 | `topic.py` правила не путают `rain`/`Ukraine`/`China` (уже есть word-boundary фикс) | high | существующие + новые тесты |
| BET-5 | Флот из ~N кошельков поместится в дневной refresh без rate-limit | medium | C5 |

---

## 11. Зависимость от sage (API-recon)

Sage проверяет ровно: (1) полная история >500 через Data/CLOB пагинацию, (2) on-chain источник USDC/ETH, (3) есть ли `category/tag` в Data API.

**Обработка:** builder НЕ блокируется на sage. Реализует по значениям по умолчанию (BET-2/BET-3/BET-1) и в C1/C4 подтверждает факт. Если sage вернул конкретику — применить, но структура плана от этого не меняется (fallback уже встроен через KILL-1/2). Если sage молчит — builder делает 1 проверочный curl сам (read-only).

---

## 12. Definition of Done (критерии готовности)

MVP считается готовым, когда **все** пункты верны:

- [ ] `cli.py portrait <addr>` выдаёт markdown + JSON с 6 темами (+other), стратегией, PnL, on-chain секцией и `truncated`-флагом.
- [ ] Погодное ограничение снято: профиль сохраняется для любого кошелька с ≥1 BUY; `prune_non_weather` удалён.
- [ ] Полная история: `get_all_trades_full` возвращает всё, что отдаёт API, без тихого cap; окно задокументировано.
- [ ] On-chain секция показывает ≥1 депозит и ≥1 вывод на контрольном кошельке и сверку с lb-api PnL (или честно отключена по KILL-2 с пометкой).
- [ ] `status/report/query` показывают разбивку по темам; `query --topic sports` фильтрует.
- [ ] `harvest/prune` больше не удаляют не-погодных.
- [ ] Все 42 существующих теста + новые (topic accuracy, onchain parse, full-history) — зелёные.
- [ ] `strategies/weather/` и `telegram-bot/` не затронуты (git status чист по этим путям).

---

## 13. Проверяемые чекпоинты C0–C6

| # | Чекпоинт | Проверка (одна команда → ожидаемый результат) |
|---|---|---|
| C0 | `topic.py` сужен до 6+other, старые 16 тестов + новые зелёные | `pytest test_topic.py -q` → all pass |
| C1 | on-chain источник подтверждён | 1 read-only запрос PolygonScan/RPC → в логе адрес USDC + 1 Transfer |
| C2 | полная история без cap | `portrait <multitopic wallet>` → `count` > 500 (или `truncated` честно помечен) |
| C3 | тема-accuracy | gold-set 100 заголовков → `accuracy ≥ 0.80` (KILL-3 при провале) |
| C4 | on-chain сверка | контрольный кошелёк: `in>0 and out>0` + `net` в пределах допуска vs lb-api |
| C5 | флот без rate-limit | `refresh --harvest` на 20 кошельков → `err==0` |
| C6 | портрет end-to-end + изоляция | `cli.py portrait <addr> --json` валиден; `git status` чист по `strategies/weather` |

---

## 14. Файлы: изменить / создать / не трогать

**Изменить (точечно):**
- `api.py` — `get_all_trades` → `get_all_trades_full` (+window, fallback CLOB).
- `classifier.py` — `classify_wallet` использует `topic_distribution`; убрать weather-gate из `_pick_strategy`; `weather_ratio` → `topic`-поля.
- `collector.py` — схема v2 (`topics_json`, `top_topic`, `topic_concentration`); убрать `prune_non_weather`/weather-фильтр; `_migrate` добавить колонки.
- `cli.py` — новый `portrait`; `report/status/query/strategies/recommend` → topic-срезы; убрать `prune`.
- `discover.py` — live-слаги со всех тем, не только weather.

**Создать:**
- `onchain.py` — депозиты/выводы/балансы/сверка (PolygonScan → RPC fallback).
- `portrait.py` — сборка + рендер markdown/JSON (поглощает `deep_analyze_unknown.deep_profile`).
- `test_onchain.py`, `test_portrait.py`, расширение `test_topic.py` (gold-set).

**Не трогать:**
- `city_parser.py`, `metrics.py`, `config.py` (кроме добавления `POLYGONSCAN_API_KEY`), `dashboard.py`, `deep_analyze_unknown.py` (замораживаем до поглощения в `portrait.py`), `strategies/`, `telegram-bot/`, `shared/`.

---

## 15. Риски

| Риск | Вероятность | Митигация |
|---|---|---|
| Builder уходит в перестройку | medium | §2 инварианты + «изменить/создать/не трогать» + ревью diff на «не трогать» |
| Data API не отдаёт полную историю | medium | KILL-1 fallback, честный `truncated` |
| Прокси/гео из РФ ломает новые эндпоинты | low | всё через `make_http_client`, проверка на C1 |
| `profiles.db` миграция лосит данные | medium | KILL-4 пересборка |
| Тема-микс уезжает в `other` | medium | C3 gold-set, дообучение правил |

---

## Итог для оркестратора

MVP = **расширение** 6 существующих модулей + 1 новый on-chain модуль + 1 новый `portrait`-командой. Первый проверяемый результат — `cli.py portrait <addr>` на известном мультитематическом кошельке. Ждём от sage три факта (история/on-chain/категории) — но builder по ним не блокируется: fallback и kill-переключатели уже заложены (KILL-1/2/3).
