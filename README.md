# Polymarket Trading Hub

## Структура
```
polymarket/
├── shared/opencode.jsonc    # OpenCode (aimodel.lol)
├── strategies/
│   ├── weather/             # 🌤️ Погодный бот (АКТИВЕН)
│   ├── copy-trading/        # 📋 Копи-трейдинг (planned)
│   ├── sweeper/             # 🧹 Sweeper 99¢ (planned)
│   ├── range-fade/          # 📈 Range Fade (planned)
│   └── buy-low/             # 💰 Buy Low Sell Certain (planned)
├── telegram-bot/
│   ├── bot.py               # Telegram-бот
│   └── webapp.py            # Веб-интерфейс (:8099)
├── data/                    # Общие данные
└── .env                     # Ключи
```

## Команды Telegram
/start /status /pnl /positions /config /start_weather /stop_weather /logs

## Веб
http://127.0.0.1:8099 — дашборд weather

## Запуск
```bash
cd telegram-bot && python bot.py  # бот + веб
cd strategies/weather && python bot_v3.py  # только погода
```
