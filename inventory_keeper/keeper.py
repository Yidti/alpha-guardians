#!/usr/bin/env python3
"""Alpha 囤貨婆（Alpha Hoarder）：今天繳哪幾支、哪些先留、哪些作廢、下一輪研究哪一格。

只用 Python 標準函式庫（3.9+），不連任何資料庫、不呼叫 simulation API。
所有門檻都在設定檔（config.json），每個人照自己的條件改。

用法：
    python keeper.py --config config.json --data my_data/
    python keeper.py --config config.json --data my_data/ --json    # 輸出機器可讀的結果

my_data/ 裡要有：
    pyramid.json      本季每一格已繳幾支、乘數
    candidates.json   你手上驗證過的候選（/check 結果與指標）
    pairs.json        （二選一）候選之間、候選對「之後才繳的 alpha」的每日 PnL 相關
    pnl/<id>.csv      （二選一）每支的累積 PnL：date,pnl 兩欄；程式自己算相關
    submitted_after.json （用 pnl/ 時選填）候選驗證之後才繳的 alpha id 清單
格式見 README.md。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import date
from pathlib import Path

DEFAULT_CONFIG = {
    "corr_max": 0.7,
    "cell_full": 3,
    "turnover_max": 0.20,
    "require_check_pass": True,
    "edge_prod": 0.7,
    "min_pnl_days": 60,
    "score_weights": {"sharpe": 1.0, "fitness": 1.0, "worst_recent_year": 0.5,
                      "prod_corr": -2.0, "self_corr": -1.0, "turnover": -2.0, "margin": 0.25},
    "margin": {"floor_bps": 10.0, "target_bps": 15.0, "cap": 2.0,
               "low_turnover_zero": 0.01, "low_turnover_full": 0.03},
    "bonus_priority": {"enabled": False, "name": "加分條件", "regions": [],
                       "min_sharpe": 0.0, "min_fitness": 0.0, "until": None},
    "submit_tiers": [[30, 4], [20, 3], [10, 2]],
    "default_submit": 1,
    "max_submit_per_day": 4,
    "research": {"top_n": 5},
}

IN_STOCK = ("inventory", "reserve")
P_FILL, P_BONUS, P_GENERAL, P_HOLD = 1, 2, 3, 4
P_LABEL = {P_FILL: "① 能補滿格子", P_BONUS: "② 加分條件", P_GENERAL: "一般（可繳）", P_HOLD: "暫不繳"}


# ── 讀檔 ────────────────────────────────────────────────────────────────────

def merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def norm_cell(s) -> str:
    """'usa_d1_news'、'USA/D1/NEWS' → 'USA/D1/NEWS'。"""
    return str(s).strip().upper().replace("_", "/").replace(" ", "")


def load_json(p: Path, default=None):
    if not p.exists():
        if default is not None:
            return default
        sys.exit(f"找不到 {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def read_pnl_csv(p: Path) -> dict:
    """date,pnl（累積）→ {date: 當日變動}。"""
    rows = []
    with p.open(encoding="utf-8") as f:
        for r in csv.reader(f):
            if len(r) < 2:
                continue
            try:
                rows.append((r[0].strip(), float(r[1])))
            except ValueError:
                continue   # 表頭
    rows.sort()
    return {rows[i][0]: rows[i][1] - rows[i - 1][1] for i in range(1, len(rows))}


def pearson_abs(a: dict, b: dict, min_n: int):
    days = sorted(set(a) & set(b))
    if len(days) < min_n:
        return None
    x, y = [a[d] for d in days], [b[d] for d in days]
    mx, my = sum(x) / len(x), sum(y) / len(y)
    sx = math.sqrt(sum((v - mx) ** 2 for v in x))
    sy = math.sqrt(sum((v - my) ** 2 for v in y))
    if sx < 1e-12 or sy < 1e-12:
        return None
    return abs(sum((p - mx) * (q - my) for p, q in zip(x, y)) / (sx * sy))


def year_sharpes(daily: dict):
    """近一年、前一年（各 252 個交易日）年化 Sharpe。"""
    v = [daily[d] for d in sorted(daily)]

    def sh(x):
        if len(x) < 200:
            return None
        m = sum(x) / len(x)
        s = math.sqrt(sum((t - m) ** 2 for t in x) / len(x))
        return None if s < 1e-12 else round(m / s * math.sqrt(252), 2)

    return (sh(v[-252:]) if len(v) >= 252 else None, sh(v[-504:-252]) if len(v) >= 504 else None)


def load_data(d: Path, cfg: dict):
    pyr = {norm_cell(r["cell"]): r for r in load_json(d / "pyramid.json")}
    cands = load_json(d / "candidates.json")
    for c in cands:
        c["cells"] = [norm_cell(s) for s in c.get("cells") or []]
    pair_tab, after = {}, {}
    if (d / "pairs.json").exists():
        pj = load_json(d / "pairs.json")
        for a, b, v in pj.get("pairs", []):
            pair_tab[tuple(sorted((a, b)))] = v
        after = {k: [tuple(x) for x in v] for k, v in (pj.get("after_submits") or {}).items()}
    elif (d / "pnl").is_dir():
        pnl = {p.stem: read_pnl_csv(p) for p in (d / "pnl").glob("*.csv")}
        ids = [c["alpha_id"] for c in cands]
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if a in pnl and b in pnl:
                    pair_tab[tuple(sorted((a, b)))] = pearson_abs(pnl[a], pnl[b], cfg["min_pnl_days"])
        for sid in load_json(d / "submitted_after.json", default=[]):
            for a in ids:
                if a in pnl and sid in pnl:
                    after.setdefault(a, []).append((sid, pearson_abs(pnl[a], pnl[sid], cfg["min_pnl_days"])))
        for c in cands:
            c["has_pnl"] = c["alpha_id"] in pnl
            if c["has_pnl"] and c.get("yr_sharpe_last") is None:
                c["yr_sharpe_last"], c["yr_sharpe_prev"] = year_sharpes(pnl[c["alpha_id"]])
    else:
        sys.exit("要有 pairs.json 或 pnl/ 資料夾，才算得出庫存之間會不會打架")
    for c in cands:
        c.setdefault("has_pnl", True)

    def pair(a, b):
        return pair_tab.get(tuple(sorted((a, b))))

    return pyr, cands, pair, after


# ── 規則 ────────────────────────────────────────────────────────────────────

def margin_unit(margin, turnover, sharpe, m: dict) -> float:
    if margin is None:
        return 0.0
    bps = float(margin) * 10000.0 * (-1 if sharpe is not None and float(sharpe) < 0 else 1)
    unit = (bps - m["floor_bps"]) / (m["target_bps"] - m["floor_bps"])
    unit = max(-m["cap"], min(m["cap"], unit))
    if unit > 0:   # 換手太低時 margin 會被灌大：只打折加分
        t = float(turnover or 0.0)
        unit *= max(0.0, min(1.0, (t - m["low_turnover_zero"]) / (m["low_turnover_full"] - m["low_turnover_zero"])))
    return unit


def score(c: dict, cfg: dict):
    w, parts, miss = cfg["score_weights"], [], []

    def g(k):
        if c.get(k) is None:
            miss.append(k)
            return 0.0
        return float(c[k])

    total = (w["sharpe"] * g("sharpe") + w["fitness"] * g("fitness") + w["prod_corr"] * g("prod_corr")
             + w["self_corr"] * g("self_corr") + w["turnover"] * g("turnover"))
    yrs = [y for y in (c.get("yr_sharpe_last"), c.get("yr_sharpe_prev")) if y is not None]
    if len(yrs) == 2:
        total += w["worst_recent_year"] * min(yrs)
        parts.append(f"近兩年較差那年 Sharpe {min(yrs):.2f}")
    else:
        miss.append("逐年 Sharpe")
    if w.get("margin") and c.get("margin") is not None:
        bonus = w["margin"] * margin_unit(c["margin"], c.get("turnover"), c.get("sharpe"), cfg["margin"])
        total += bonus
        parts.append(f"margin {float(c['margin']) * 10000:.1f} bps（{bonus:+.2f}）")
    text = (f"Sharpe {g('sharpe'):.2f}、Fitness {g('fitness'):.2f}、prod {g('prod_corr'):.3f}、"
            f"self {g('self_corr'):.3f}、換手 {g('turnover'):.3f}"
            + ("、" + "、".join(parts) if parts else "") + (f"（缺 {'、'.join(miss)}，當 0）" if miss else ""))
    return round(total, 3), text


def bonus_ok(c: dict, cfg: dict, today: str) -> bool:
    b = cfg["bonus_priority"]
    if not b.get("enabled"):
        return False
    if b.get("until") and today > b["until"]:
        return False
    region = str(c.get("region") or (c["cells"][0].split("/")[0] if c["cells"] else "")).upper()
    if b.get("regions") and region not in [r.upper() for r in b["regions"]]:
        return False
    try:
        return float(c["sharpe"]) > b["min_sharpe"] and float(c["fitness"]) > b["min_fitness"]
    except (KeyError, TypeError, ValueError):
        return False


def plan(pyr: dict, cands: list, pair, after: dict, cfg: dict, today: str) -> dict:
    """每支候選的決定：inventory（能補格子）／reserve（格子已滿，仍算庫存）／displaced（被取代）／
    blocked（不符你的條件）／unknown（資料不夠，不猜）。"""
    full, cmax = cfg["cell_full"], cfg["corr_max"]
    sub = {k: int(v.get("submitted") or 0) for k, v in pyr.items()}
    scored = sorted(((*score(c, cfg), c) for c in cands), key=lambda x: (-x[0], x[2]["alpha_id"]))
    out, inv, res, used = {}, [], [], {}

    for s, txt, c in scored:
        aid = c["alpha_id"]
        d = out[aid] = {"alpha_id": aid, "score": s, "score_text": txt, "cells": c["cells"], "displaced_by": None}
        if cfg["require_check_pass"] and (c.get("prod_check") != "PASS" or c.get("self_check") != "PASS"):
            d.update(admission="blocked", reason=f"平台 /check：PROD {c.get('prod_check') or '沒資料'}、"
                                                 f"SELF {c.get('self_check') or '沒資料'}，不是 PASS（還在算的話晚點重匯出）")
            continue
        if cfg.get("turnover_max") is not None and c.get("turnover") is not None \
                and float(c["turnover"]) > cfg["turnover_max"]:
            d.update(admission="blocked", reason=f"換手 {float(c['turnover']):.1%} > 你設的上限 {cfg['turnover_max']:.0%}")
            continue
        if not c["cells"]:
            d.update(admission="unknown", reason="不知道落在哪一格（cells 是空的）")
            continue
        if not c.get("has_pnl"):
            d.update(admission="unknown", reason="缺 PnL，算不出會不會跟庫存打架")
            continue
        hit = [(sid, v) for sid, v in after.get(aid, []) if v is None or v >= cmax]
        if hit:
            sid, v = hit[0]
            d.update(admission="unknown" if v is None else "displaced", displaced_by=None if v is None else sid,
                     reason=(f"之後才繳的 {sid} 查不到 PnL，要重驗" if v is None
                             else f"跟之後才繳的 {sid} 相關 {v:.3f} ≥ {cmax}，繳了會 SELF_CORRELATION FAIL"))
            continue
        clash = next(((o, pair(aid, o["alpha_id"])) for o in inv
                      if pair(aid, o["alpha_id"]) is None or pair(aid, o["alpha_id"]) >= cmax), None)
        if clash:
            o, v = clash
            d.update(admission="unknown" if v is None else "displaced", displaced_by=None if v is None else o["alpha_id"],
                     reason=(f"查不到跟庫存 {o['alpha_id']} 的相關" if v is None
                             else f"被 {o['alpha_id']} 取代：相關 {v:.3f} ≥ {cmax}，對方分數 {o['score']:.2f} 較高"))
            continue
        room = [k for k in d["cells"] if sub.get(k, 0) + used.get(k, 0) < full]
        if room:
            k = room[0]
            d.update(admission="inventory",
                     reason=f"入庫：{k} 本季已繳 {sub.get(k, 0)}、庫存先前 {used.get(k, 0)} 支")
            for kk in d["cells"]:
                used[kk] = used.get(kk, 0) + 1
            inv.append(d)
            for r in list(res):   # 能補格子的優先：跟它打架的保留區那支讓位
                v = pair(aid, r["alpha_id"])
                if v is None or v >= cmax:
                    r.update(admission="unknown" if v is None else "displaced",
                             displaced_by=None if v is None else aid,
                             reason=(f"查不到跟庫存 {aid} 的相關" if v is None
                                     else f"被 {aid} 取代：相關 {v:.3f} ≥ {cmax}，{aid} 能補格子（優先）"))
                    res.remove(r)
            continue
        o = next((x for x in res if (pair(aid, x["alpha_id"]) or 0) >= cmax), None)
        if o:
            d.update(admission="displaced", displaced_by=o["alpha_id"],
                     reason=f"被 {o['alpha_id']} 取代（保留區內）：相關 {pair(aid, o['alpha_id']):.3f} ≥ {cmax}")
            continue
        d.update(admission="reserve", reason="格子已滿（" + "、".join(
            f"{x} 已繳 {sub.get(x, 0)}＋庫存 {used.get(x, 0)}" for x in d["cells"]) + f"，≥ {full}），繳了不多解 pyramid")
        res.append(d)

    # 繳交優先序：用最後留在 inventory 的同格支數，看補不補得滿
    inv_by = {}
    for x in out.values():
        if x.get("admission") == "inventory":
            for k in x["cells"]:
                inv_by[k] = inv_by.get(k, 0) + 1
    by_id = {c["alpha_id"]: c for c in cands}
    for aid, d in out.items():
        if d["admission"] not in IN_STOCK:
            d["priority"] = None
            continue
        fills = [(k, sub.get(k, 0), inv_by.get(k, 0)) for k in d["cells"]]
        fillable = any(s0 < full <= s0 + i0 for _, s0, i0 in fills)
        open_cell = any(s0 < full for _, s0, _ in fills)
        if d["admission"] == "inventory" and fillable:
            d["priority"] = P_FILL
        elif bonus_ok(by_id[aid], cfg, today):
            d["priority"] = P_BONUS
        elif d["admission"] == "inventory" and open_cell:
            d["priority"] = P_GENERAL
        else:
            d["priority"] = P_HOLD
        d["edge"] = by_id[aid].get("prod_corr") is not None and float(by_id[aid]["prod_corr"]) >= cfg["edge_prod"]
    return out


def closing_cell(d: dict, sub: dict, full: int):
    return next((k for k in d["cells"] if sub.get(k, 0) == full - 1), None)


def rank(out: dict, pyr: dict, cfg: dict) -> list:
    """今天先繳的順序：優先序 → 繳了剛好補滿一格 → 邊緣（prod ≥ 門檻、/check 判 PASS）→ 分數 → id。"""
    sub = {k: int(v.get("submitted") or 0) for k, v in pyr.items()}
    pool = [d for d in out.values() if d.get("priority") in (P_FILL, P_BONUS, P_GENERAL)]
    return sorted(pool, key=lambda d: (d["priority"], 0 if closing_cell(d, sub, cfg["cell_full"]) else 1,
                                       0 if d.get("edge") else 1, -d["score"], d["alpha_id"]))


def how_many(stock: int, n_ready: int, cfg: dict) -> int:
    """看「繳完還剩幾支」決定今天繳幾支：繳 n 支後剩 ≥ 門檻才繳 n 支。"""
    best = cfg["default_submit"]
    for threshold, n in cfg["submit_tiers"]:
        if stock - n >= threshold:
            best = max(best, n)
    return max(0, min(best, cfg["max_submit_per_day"], n_ready))


def research(out: dict, pyr: dict, cfg: dict) -> dict:
    full = cfg["cell_full"]
    sub = {k: int(v.get("submitted") or 0) for k, v in pyr.items()}
    mult = {k: v.get("multiplier") for k, v in pyr.items()}
    stock = {}
    for d in out.values():
        if d.get("admission") in IN_STOCK:
            for k in d["cells"]:
                stock[k] = stock.get(k, 0) + 1
    fill = sorted(((k, sub.get(k, 0), n, full - sub.get(k, 0) - n) for k, n in stock.items()
                   if sub.get(k, 0) < full and sub.get(k, 0) + n < full), key=lambda x: (x[3], x[0]))
    partial = sorted(((k, sub[k], mult.get(k), full - sub[k]) for k in sub if 0 < sub[k] < full and k not in stock),
                     key=lambda x: (x[3], -(x[2] or 0), x[0]))
    stop = sorted(((k, sub[k], stock.get(k, 0)) for k in sub if sub[k] >= full),
                  key=lambda x: (-(x[1] + x[2]), x[0]))
    n = cfg["research"]["top_n"]
    return {"fill_with_stock": fill[:n], "partial_no_stock": partial[:n], "stop": stop[:n],
            "overfilled": sum(max(0, s - full) for s in sub.values())}


# ── 輸出 ────────────────────────────────────────────────────────────────────

def report(out: dict, order: list, n: int, rs: dict, cfg: dict) -> str:
    stock = [d for d in out.values() if d.get("admission") in IN_STOCK]
    L = [f"庫存 {len(stock)} 支（能補格子 {sum(d['admission'] == 'inventory' for d in stock)}、"
         f"格子已滿 {sum(d['admission'] == 'reserve' for d in stock)}）"
         f"｜被取代 {sum(d['admission'] == 'displaced' for d in out.values())}"
         f"｜不符條件 {sum(d['admission'] == 'blocked' for d in out.values())}"
         f"｜資料不夠 {sum(d['admission'] == 'unknown' for d in out.values())}", ""]
    L.append(f"【今天繳 {n} 支】（庫存 {len(stock)}，繳完剩 {len(stock) - n}）")
    sub_full = cfg["cell_full"]
    for i, d in enumerate(order[:n], 1):
        L.append(f"  {i}. {d['alpha_id']}  {P_LABEL[d['priority']]}  分數 {d['score']:.2f}  {'、'.join(d['cells'])}")
    L.append("  ※ 每一支繳之前再打一次平台 /check，PASS 才繳。")
    if order[n:]:
        L.append("\n【排隊中，明天以後】")
        for d in order[n:n + 5]:
            L.append(f"  {d['alpha_id']}  {P_LABEL[d['priority']]}  分數 {d['score']:.2f}")
    hold = [d for d in stock if d["priority"] == P_HOLD]
    if hold:
        L.append("\n【先留著（暫不繳）】" + "、".join(d["alpha_id"] for d in hold))
    gone = [d for d in out.values() if d["admission"] == "displaced"]
    if gone:
        L.append("\n【作廢：繳了會 SELF FAIL】")
        for d in gone:
            L.append(f"  {d['alpha_id']}：{d['reason']}")
    L.append("\n【下一輪研究】")
    for k, s, st, need in rs["fill_with_stock"]:
        L.append(f"  去補：{k}（已繳 {s}＋庫存 {st}，還差 {need}）")
    for k, s, m, need in rs["partial_no_stock"]:
        L.append(f"  去補：{k}（已繳 {s}、庫存沒有，還差 {need}，乘數 {m if m is not None else '?'}）")
    for k, s, st in rs["stop"]:
        if st:
            L.append(f"  別再做：{k}（本季已繳 {s}，庫存還有 {st} 支同格）")
    if rs["overfilled"]:
        L.append(f"  本季繳進已滿格子、沒多解 pyramid 的：{rs['overfilled']} 支（超過 {sub_full} 支的部分）")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="囤貨婆")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--data", default="data")
    ap.add_argument("--today", default=date.today().isoformat(), help="YYYY-MM-DD（加分條件的截止日用）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    cfg = merge(DEFAULT_CONFIG, load_json(Path(a.config), default={}))
    pyr, cands, pair, after = load_data(Path(a.data), cfg)
    out = plan(pyr, cands, pair, after, cfg, a.today)
    order = rank(out, pyr, cfg)
    stock = sum(d.get("admission") in IN_STOCK for d in out.values())
    n = how_many(stock, len(order), cfg)
    rs = research(out, pyr, cfg)
    if a.json:
        print(json.dumps({"decisions": out, "order": [d["alpha_id"] for d in order], "submit_today": n,
                          "research": rs}, ensure_ascii=False, indent=1))
    else:
        print(report(out, order, n, rs, cfg))


if __name__ == "__main__":
    main()
