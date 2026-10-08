import os, json, glob

BASE = "/Users/alexander/projects/polymarket/strategies"

def first_readme_line(d):
    r = os.path.join(d, "README.md")
    if not os.path.exists(r):
        return ""
    try:
        txt = open(r, encoding="utf-8", errors="ignore").read()
    except:
        return ""
    for line in txt.splitlines():
        line = line.strip()
        if line and not line.startswith(("```", "<", "!", "[!")):
            # убрать markdown заголовки и теги
            line = line.lstrip("#").strip()
            if line:
                return line[:140]
    return ""

def has(d, name):
    return os.path.exists(os.path.join(d, name))

rows = []
for d in sorted(glob.glob(f"{BASE}/*")):
    if not os.path.isdir(d):
        continue
    name = os.path.basename(d)
    desc = first_readme_line(d)
    # признаки активности/данных
    signals = []
    if has(d, "logs"): signals.append("logs")
    if has(d, "data"): signals.append("data")
    if has(d, "state.json"): signals.append("state")
    # balance из state/config
    bal = None
    for f in ("data/state.json", "state.json", "data/portfolio.json"):
        p = os.path.join(d, f)
        if os.path.exists(p):
            try:
                j = json.load(open(p))
                for k in ("balance", "bankroll", "equity"):
                    if k in j:
                        bal = j[k]; break
            except:
                pass
            if bal is not None:
                break
    rows.append((name, desc, signals, bal))

print(f"Всего стратегий: {len(rows)}\n")
for name, desc, signals, bal in rows:
    b = f"${bal:,.2f}" if isinstance(bal, (int, float)) else "—"
    sig = ",".join(signals) if signals else "—"
    print(f"### {name}")
    print(f"   {desc}")
    print(f"   баланс: {b} | активность: {sig}")
    print()
