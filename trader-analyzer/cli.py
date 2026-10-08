#!/usr/bin/env python3
"""
cli.py — единая точка входа trader-analyzer.

  python cli.py parse "Will the highest temperature in London be 20°C or below on August 19?"
  python cli.py status
  python cli.py report
  python cli.py report --json
  python cli.py recommend
  python cli.py recommend --hours 24
  python cli.py add 0xabc... --name WeatherHk
  python cli.py collect
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def cmd_parse(args: argparse.Namespace) -> int:
    from city_parser import parse_market, parse_outcome

    info = parse_market(args.title)
    if args.outcome:
        extra = parse_outcome(args.outcome)
        if extra["degree"] is not None:
            info["degree"] = extra["degree"]
            info["unit"] = extra["unit"] or info["unit"]
            info["bound"] = extra["bound"] or info["bound"]
            if info["kind"] == "other":
                info["kind"] = "temperature"
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from collector import get_all_profiles
    from config import DB_PATH, SIGNAL_RECENCY_HOURS, WEATHER_MIN_RATIO

    weather = get_all_profiles(weather_only=True)
    all_rows = get_all_profiles(weather_only=False)
    by_strategy = Counter(p["strategy"] for p in weather)
    by_topic = Counter(p.get("top_topic") for p in all_rows)
    print(f"db: {DB_PATH}")
    print(f"profiles: {len(all_rows)} total, {len(weather)} weather (≥{WEATHER_MIN_RATIO})")
    with_pnl = sum(1 for p in weather if p.get("pnl") is not None)
    with_act = sum(1 for p in weather if p.get("trades_30d") is not None)
    print(f"metrics: pnl={with_pnl}/{len(weather)}  activity_30d={with_act}/{len(weather)}")
    print(f"recency window: {SIGNAL_RECENCY_HOURS}h")
    print("topics:")
    for topic, n in by_topic.most_common():
        print(f"  {str(topic):16s} {n}")
    print("strategies:")
    for strat, n in by_strategy.most_common():
        print(f"  {strat:12s} {n}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from collector import get_all_profiles

    rows = get_all_profiles(weather_only=not args.all)
    payload = {
        "count": len(rows),
        "by_strategy": dict(Counter(p["strategy"] for p in rows)),
        "by_topic": dict(Counter(p.get("top_topic") for p in rows)),
        "profiles": [
            {
                "wallet": p["wallet"],
                "name": p["name"],
                "strategy": p["strategy"],
                "top_city": p["top_city"],
                "top_topic": p.get("top_topic"),
                "topic_concentration": p.get("topic_concentration"),
                "weather_ratio": p["weather_ratio"],
                "median_entry": p["median_entry"],
                "city_concentration": p["city_concentration"],
                "buy_trades": p["buy_trades"],
            }
            for p in rows
        ],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"# Traders — {payload['count']}\n")
    print("## Strategies")
    for strat, n in sorted(payload["by_strategy"].items(), key=lambda x: -x[1]):
        print(f"- {strat}: {n}")
    print("\n## Topics")
    for topic, n in sorted(payload["by_topic"].items(), key=lambda x: -x[1]):
        print(f"- {topic}: {n}")
    print("\n## Profiles")
    for p in payload["profiles"]:
        print(
            f"- {p['name']} [{p['strategy']}] {p['top_city']} "
            f"topic={p['top_topic']} weather={p['weather_ratio']} "
            f"median={p['median_entry']} conc={p['city_concentration']}"
        )
    return 0


def cmd_recommend(args: argparse.Namespace) -> int:
    from recommend import format_recommendations, recommend_from_ladder_traders

    recs = recommend_from_ladder_traders(hours=args.hours)
    if args.json:
        print(json.dumps(recs, ensure_ascii=False, indent=2))
        return 0
    print(format_recommendations(recs, hours=args.hours))
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    from collector import add_wallet

    profile = add_wallet(args.wallet, name=args.name)
    print(json.dumps({
        "wallet": args.wallet,
        "strategy": profile.get("strategy"),
        "weather_ratio": profile.get("weather_ratio"),
        "top_city": profile.get("top_city"),
        "median_entry": profile.get("median_entry"),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    from collector import collect_known, get_all_profiles

    collect_known(verbose=True)
    print(f"\nweather profiles: {len(get_all_profiles())}")
    return 0


def cmd_reclassify(args: argparse.Namespace) -> int:
    from collector import get_all_profiles, upsert_profile

    rows = get_all_profiles(weather_only=False)
    for i, p in enumerate(rows, 1):
        try:
            profile = upsert_profile(p["wallet"], name=p["name"], max_trades=args.max_trades)
            print(
                f"  [{i}/{len(rows)}] {p['name']}: {p['strategy']} → {profile.get('strategy')} "
                f"weather={profile.get('weather_ratio')}",
                flush=True,
            )
        except Exception as e:
            print(f"  [{i}/{len(rows)}] {p['name']}: ERR {e}", flush=True)
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    from discover import discover_candidates

    result = discover_candidates(include_live_markets=not args.leaderboards_only)
    print(f"leaderboards: {result['leaderboards']}")
    print(f"live_markets: {result['live_markets']}")
    print(f"unique: {result['unique']}")
    if args.json:
        print(json.dumps(result["traders"], ensure_ascii=False, indent=2))
    else:
        for t in result["traders"][:30]:
            print(f"  {t.get('name') or t['address'][:12]}  {','.join(t['sources'])}")
        if result["unique"] > 30:
            print(f"  ... +{result['unique'] - 30}")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    from collector import get_all_profiles, upsert_profile
    from discover import discover_candidates

    found = discover_candidates(include_live_markets=not args.leaderboards_only)
    existing = {p["wallet"].lower(): p for p in get_all_profiles(weather_only=False)}
    print(
        f"discover unique={found['unique']} (boards={found['leaderboards']} live={found['live_markets']}) "
        f"db={len(existing)}",
        flush=True,
    )

    queue: dict[str, str | None] = {}
    for p in existing.values():
        queue[p["wallet"].lower()] = p.get("name")
    for t in found["traders"]:
        addr = t["address"]
        if addr not in queue:
            queue[addr] = t.get("name")
        elif t.get("name") and (not queue[addr] or queue[addr] in ("unknown", addr)):
            queue[addr] = t["name"]

    items = list(queue.items())
    if args.limit:
        items = items[: args.limit]
    print(f"upsert {len(items)} wallets (max_trades={args.max_trades})", flush=True)

    ok = err = 0
    for i, (wallet, name) in enumerate(items, 1):
        try:
            profile = upsert_profile(wallet, name=name, max_trades=args.max_trades)
            ok += 1
            print(
                f"  [{i}/{len(items)}] {name or wallet[:10]} → {profile.get('strategy')} "
                f"weather={profile.get('weather_ratio')} city={profile.get('top_city')}",
                flush=True,
            )
        except Exception as e:
            err += 1
            print(f"  [{i}/{len(items)}] {name or wallet[:10]} ERR {e}", flush=True)

    from collector import get_all_profiles as _all
    weather = _all(weather_only=True)
    print(f"\ndone ok={ok} err={err} weather_profiles={len(weather)} total={len(_all(False))}")
    return 0 if err == 0 else 1


def cmd_harvest(args: argparse.Namespace) -> int:
    """Живые события → скрин → в БД все кошельки с >= min_buys BUY."""
    from collector import get_all_profiles, screen_wallet
    from discover import fetch_live_market_traders

    existing = {p["wallet"].lower() for p in get_all_profiles(weather_only=False)}
    live = fetch_live_market_traders(
        min_hits=args.min_hits,
        max_events=args.max_events,
        per_event=args.per_event,
        days=2,
    )
    new = [t for t in live if t["address"] not in existing]
    new.sort(key=lambda t: t.get("market_hits") or 0, reverse=True)
    if args.limit:
        new = new[: args.limit]
    print(
        f"live={len(live)} new={len(new)} min_hits={args.min_hits} "
        f"already={len(existing)}",
        flush=True,
    )

    kept = skipped = err = 0
    for i, t in enumerate(new, 1):
        try:
            profile = screen_wallet(
                t["address"],
                max_trades=args.max_trades,
                min_buys=args.min_buys,
            )
            if profile is None:
                skipped += 1
                if args.verbose:
                    print(f"  [{i}/{len(new)}] skip hits={t.get('market_hits')}", flush=True)
                continue
            kept += 1
            print(
                f"  [{i}/{len(new)}] KEEP hits={t.get('market_hits')} "
                f"{profile.get('strategy')} weather={profile.get('weather_ratio')} "
                f"city={profile.get('top_city')}",
                flush=True,
            )
        except Exception as e:
            err += 1
            print(f"  [{i}/{len(new)}] ERR {e}", flush=True)

    from collector import get_all_profiles as _all
    print(
        f"\ndone kept={kept} skipped={skipped} err={err} "
        f"weather={len(_all(True))} total={len(_all(False))}",
        flush=True,
    )
    return 0 if err == 0 else 1


def cmd_strategies(args: argparse.Namespace) -> int:
    from rank_strategies import format_rank, rank_weather, write_rank

    payload = rank_weather(playbook_only=not args.all_weather, with_pnl=not args.no_pnl)
    write_rank(payload)
    text = format_rank(payload, top=args.top)
    print(text)
    return 0


def cmd_signals(args: argparse.Namespace) -> int:
    from signals import generate, send_telegram

    text = generate()
    print(text)
    if args.telegram:
        ok = send_telegram(text)
        print("telegram: sent" if ok else "telegram: skipped (no TG_SIGNAL_TOKEN)")
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    from query import query_profiles

    playbook = None
    if args.playbook:
        playbook = True
    elif args.no_playbook:
        playbook = False
    rows = query_profiles(
        weather_only=not args.all,
        strategy=args.strategy,
        city=args.city,
        topic=args.topic,
        min_pnl=args.min_pnl,
        max_pnl=args.max_pnl,
        min_month=args.min_month,
        min_trades_30d=args.min_trades_30d,
        min_volume_30d=args.min_volume,
        min_active_days=args.min_active_days,
        min_weather=args.min_weather,
        min_entry=args.min_entry,
        max_entry=args.max_entry,
        min_conc=args.min_conc,
        playbook=playbook,
        sort=args.sort,
        desc=not args.asc,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"{len(rows)} wallets  sort={args.sort}")
    for p in rows:
        pnl = p.get("pnl")
        pnl_s = "n/a" if pnl is None else f"${pnl:,.0f}"
        tpm = p.get("trades_per_month")
        t30 = p.get("trades_30d")
        print(
            f"- {p.get('name')} [{p.get('strategy')}] {p.get('top_city')}  "
            f"topic={p.get('top_topic')}  "
            f"PnL {pnl_s}  /mo={tpm}  30d={t30}  "
            f"weather={p.get('weather_ratio')} entry={p.get('median_entry')}  "
            f"{(p.get('wallet') or '')[:10]}"
        )
    return 0


def cmd_portrait(args: argparse.Namespace) -> int:
    from portrait import build_portrait

    portrait = build_portrait(
        args.wallet,
        name=args.name,
        max_trades=args.max_trades,
    )
    if args.json:
        print(json.dumps(portrait, ensure_ascii=False, indent=2, default=str))
        return 0

    p = portrait
    print(f"# Portrait — {p['name']} [{p['strategy']}]")
    print(f"wallet: {p['wallet']}")
    print(f"PnL: {p['pnl'] if p['pnl'] is not None else 'n/a'}")
    w = p["window"]
    print(f"history: {w['count']} trades  {w['from']} → {w['to']}  "
          f"truncated={p['truncated']}")
    print(f"\n## Topics (top: {p['top_topic']})")
    for topic, n in sorted(p["topics"].items(), key=lambda x: -x[1]):
        print(f"- {topic}: {n}")
    prof = p["profile"]
    print("\n## Profile")
    for k in (
        "ladder_ratio", "longshot_ratio", "certain_ratio", "weather_ratio",
        "median_entry", "avg_entry", "top_city", "city_concentration",
        "buy_trades", "total_trades",
    ):
        print(f"- {k}: {prof.get(k)}")
    oc = p["onchain"]
    print("\n## On-chain")
    if not oc.get("enabled"):
        print(f"- disabled: {oc.get('reason')}")
    else:
        fl = oc.get("flow") or {}
        i_, o_ = fl.get("in") or {}, fl.get("out") or {}
        net = fl.get("net") or {}
        print(f"- deposits: {i_.get('count')} total={i_.get('total')}")
        print(f"- withdrawals: {o_.get('count')} total={o_.get('total')}")
        print(f"- net: {net.get('total')}")
        if oc.get("reconcile"):
            rec = oc["reconcile"]
            print(f"- reconcile vs lb-api PnL: {rec.get('verdict')} "
                  f"(net={rec.get('net_flow')} pnl={rec.get('pnl')} "
                  f"delta={rec.get('delta')})")
    wd = p["withdrawals"]
    print(f"- withdrawal_stats: count={wd.get('count')} "
          f"total={wd.get('total')} dests={wd.get('n_destinations')}")
    act = p["activity"]
    print(f"\n## Activity\n- trades_30d: {act.get('trades_30d')} "
          f"buys_30d: {act.get('buys_30d')} volume_30d: {act.get('volume_30d')}")
    print(f"\n## History ({p['history_count']} trades)")
    for t in p["history"][:20]:
        print(f"- {t['side']} {t['topic']:12s} {t['price']} x {t['size']}  {t['title'][:60]}")
    if p["history_count"] > 20:
        print(f"  ... +{p['history_count'] - 20} more")
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    from collector import refresh_pnl_only, refresh_queue, refresh_wallet
    from config import REFRESH_STALE_HOURS, make_http_client

    if args.harvest:
        harvest_ns = argparse.Namespace(
            min_hits=args.min_hits, min_buys=1, max_trades=150,
            max_events=50, per_event=800, limit=0, verbose=False,
        )
        cmd_harvest(harvest_ns)

    stale_hours = REFRESH_STALE_HOURS if args.stale_hours is None else args.stale_hours
    queue = refresh_queue(stale_hours=stale_hours)
    if args.limit:
        queue = queue[: args.limit]
    print(f"refresh queue {len(queue)} (stale_hours={stale_hours} pnl_only={args.pnl_only})", flush=True)
    http = make_http_client(timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    ok = err = 0
    try:
        for i, row in enumerate(queue, 1):
            try:
                if args.pnl_only:
                    pnl = refresh_pnl_only(row["wallet"], http=http)
                    print(f"  [{i}/{len(queue)}] {row['name']} pnl={pnl}", flush=True)
                else:
                    p = refresh_wallet(
                        row["wallet"], name=row["name"],
                        max_trades=args.max_trades, with_pnl=not args.no_pnl, http=http,
                    )
                    print(
                        f"  [{i}/{len(queue)}] {row['name']} {p.get('strategy')} "
                        f"pnl={p.get('pnl')} /mo={p.get('trades_per_month')} "
                        f"30d={p.get('trades_30d')}",
                        flush=True,
                    )
                ok += 1
            except Exception as e:
                err += 1
                print(f"  [{i}/{len(queue)}] {row['name']} ERR {e}", flush=True)
    finally:
        http.close()
    print(f"done ok={ok} err={err}", flush=True)
    return 0 if err == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cli.py", description="Polymarket weather wallet analyzer")
    sub = p.add_subparsers(dest="cmd", required=True)

    parse_p = sub.add_parser("parse", help="разобрать заголовок рынка")
    parse_p.add_argument("title")
    parse_p.add_argument("--outcome", help="имя исхода, если градус не в title")
    parse_p.set_defaults(func=cmd_parse)

    st = sub.add_parser("status", help="сколько профилей в БД")
    st.set_defaults(func=cmd_status)

    rp = sub.add_parser("report", help="сводка по профилям")
    rp.add_argument("--json", action="store_true")
    rp.add_argument("--all", action="store_true", help="включая не-погодных")
    rp.set_defaults(func=cmd_report)

    rec = sub.add_parser("recommend", help="лестницы для бота")
    rec.add_argument("--hours", type=int, default=None, help="окно свежести; 0 = вся история")
    rec.add_argument("--json", action="store_true")
    rec.set_defaults(func=cmd_recommend)

    add = sub.add_parser("add", help="добавить кошелёк")
    add.add_argument("wallet")
    add.add_argument("--name")
    add.set_defaults(func=cmd_add)

    col = sub.add_parser("collect", help="собрать KNOWN_WALLETS")
    col.set_defaults(func=cmd_collect)

    rc = sub.add_parser("reclassify", help="переклассифицировать все профили из API")
    rc.add_argument("--max-trades", type=int, default=300)
    rc.set_defaults(func=cmd_reclassify)

    disc = sub.add_parser("discover", help="живые лидерборды + трейдеры сегодняшних рынков")
    disc.add_argument("--leaderboards-only", action="store_true")
    disc.add_argument("--json", action="store_true")
    disc.set_defaults(func=cmd_discover)

    ing = sub.add_parser("ingest", help="discover + upsert/reclassify в profiles.db")
    ing.add_argument("--leaderboards-only", action="store_true")
    ing.add_argument("--max-trades", type=int, default=300)
    ing.add_argument("--limit", type=int, default=0, help="обрезать очередь (0 = все)")
    ing.set_defaults(func=cmd_ingest)

    hv = sub.add_parser("harvest", help="с живых рынков брать кошельки с >= min_buys BUY")
    hv.add_argument("--min-hits", type=int, default=3, help="минимум появлений в ленте события")
    hv.add_argument("--min-buys", type=int, default=1)
    hv.add_argument("--max-trades", type=int, default=150)
    hv.add_argument("--max-events", type=int, default=50)
    hv.add_argument("--per-event", type=int, default=800)
    hv.add_argument("--limit", type=int, default=0)
    hv.add_argument("--verbose", action="store_true")
    hv.set_defaults(func=cmd_harvest)

    pt = sub.add_parser("portrait", help="полный портрет кошелька (markdown+JSON)")
    pt.add_argument("wallet")
    pt.add_argument("--name")
    pt.add_argument("--max-trades", type=int, default=1000)
    pt.add_argument("--json", action="store_true")
    pt.set_defaults(func=cmd_portrait)

    stg = sub.add_parser("strategies", help="ранг рабочих weather-стратегий по PnL")
    stg.add_argument("--all-weather", action="store_true", help="включая certain")
    stg.add_argument("--no-pnl", action="store_true")
    stg.add_argument("--top", type=int, default=25)
    stg.set_defaults(func=cmd_strategies)

    q = sub.add_parser("query", help="фильтр базы: PnL, активность/мес, стратегия, тема, город")
    q.add_argument("--strategy", help="ladder,value,specialist или через запятую")
    q.add_argument("--city")
    q.add_argument("--topic", help="weather,politics,sports,crypto,science,pop_culture,other или через запятую")
    q.add_argument("--min-pnl", type=float)
    q.add_argument("--max-pnl", type=float)
    q.add_argument("--min-month", type=float, help="сделок в пересчёте на месяц")
    q.add_argument("--min-trades-30d", type=int)
    q.add_argument("--min-volume", type=float, help="номинал за 30д (size*price)")
    q.add_argument("--min-active-days", type=int)
    q.add_argument("--min-weather", type=float)
    q.add_argument("--min-entry", type=float)
    q.add_argument("--max-entry", type=float)
    q.add_argument("--min-conc", type=float, help="концентрация на топ-городе")
    q.add_argument("--playbook", action="store_true")
    q.add_argument("--no-playbook", action="store_true")
    q.add_argument("--all", action="store_true")
    q.add_argument("--sort", default="pnl", help="pnl,trades_per_month,trades_30d,volume_30d,weather_ratio,topic_concentration,...")
    q.add_argument("--asc", action="store_true")
    q.add_argument("--limit", type=int, default=40)
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_query)

    rf = sub.add_parser("refresh", help="обновить метрики/PnL; опционально добрать новые")
    rf.add_argument("--harvest", action="store_true")
    rf.add_argument("--pnl-only", action="store_true", help="только официальный PnL, без сделок")
    rf.add_argument("--no-pnl", action="store_true")
    rf.add_argument("--stale-hours", type=float, default=None)
    rf.add_argument("--limit", type=int, default=0)
    rf.add_argument("--max-trades", type=int, default=250)
    rf.add_argument("--min-hits", type=int, default=3)
    rf.set_defaults(func=cmd_refresh)

    sig = sub.add_parser("signals", help="записать daily_signals.md")
    sig.add_argument("--telegram", action="store_true")
    sig.set_defaults(func=cmd_signals)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
