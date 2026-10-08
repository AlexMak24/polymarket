"""
signals.py — Фаза 4: утренняя сводка по weather-кошелькам.

Читает профили из profiles.db, группирует по стратегиям и городам,
генерирует Markdown-сводку. НЕ трогает работающий weather-бот.

Сводка сохраняется в daily_signals.md. Опционально — отправка в Telegram
через отдельный токен TG_SIGNAL_TOKEN (не пересекается с основным ботом).
"""

import os
from datetime import datetime
from pathlib import Path
from collections import Counter

from collector import get_all_profiles

OUT = Path(__file__).parent / "daily_signals.md"


def _summarize(profiles: list[dict]) -> str:
    """Собирает текст сводки."""
    if not profiles:
        return "Нет профилей в БД. Запусти collector.collect_known()."

    lines = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines.append(f"# Сводка weather-трейдеров — {now}\n")

    # Группировка по стратегии
    by_strategy = Counter(p["strategy"] for p in profiles)
    lines.append("## Стратегии\n")
    for strat, n in by_strategy.most_common():
        lines.append(f"- **{strat}**: {n} кошельков")

    # Лестничные трейдеры (главный сигнал для нашего бота)
    ladders = [p for p in profiles if p["strategy"] == "ladder"]
    if ladders:
        lines.append("\n## Лестничные трейдеры (наш ориентир)\n")
        for p in ladders:
            lines.append(
                f"- {p['name']} → город **{p['top_city']}**, "
                f"лестница {int(p['ladder_ratio']*100)}%, "
                f"медиана входа {p['median_entry']}"
            )

    # Города
    city_counter = Counter()
    for p in profiles:
        if p["top_city"]:
            city_counter[p["top_city"]] += 1
    if city_counter:
        lines.append("\n## Города (куда смотрят трейдеры)\n")
        for city, n in city_counter.most_common():
            lines.append(f"- {city}: {n} трейдеров")

    lines.append("\n---\n*Сгенерировано signals.py — не трогает weather-бот.*")
    return "\n".join(lines)


def generate() -> str:
    """Генерирует сводку, сохраняет в файл, возвращает текст."""
    profiles = get_all_profiles()
    text = _summarize(profiles)
    OUT.write_text(text, encoding="utf-8")
    return text


def send_telegram(text: str) -> bool:
    """
    Отправляет сводку в Telegram через ОТДЕЛЬНЫЙ токен (TG_SIGNAL_TOKEN).
    Не использует токен основного бота — изолировано.
    Возвращает True если отправлено.
    """
    token = os.getenv("TG_SIGNAL_TOKEN", "").strip()
    chat_id = os.getenv("TG_SIGNAL_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False

    import httpx
    r = httpx.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=15,
    )
    return r.status_code == 200


if __name__ == "__main__":
    text = generate()
    print(text)
    print(f"\nСохранено в: {OUT}")
    if send_telegram(text):
        print("Отправлено в Telegram ✅")
    else:
        print("TG_SIGNAL_TOKEN не задан — отправка пропущена (только файл).")
