"""每日更新：抓取A股/美股行业ETF份额与净值，计算净流入，输出 data/*.json
用法: python scripts/update.py [--days 370]
"""
import csv, io, json, os, sys, time, datetime as dt
import requests
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(os.path.join(ROOT, "config", "industries.json"), encoding="utf-8"))
DATA = os.path.join(ROOT, "data")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
DAYS = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 370
S = requests.Session(); S.headers.update(UA)

def get(url, retries=4, **kw):
    for i in range(retries):
        try:
            r = S.get(url, timeout=40, **kw); r.raise_for_status(); return r
        except Exception as e:
            if i == retries - 1: raise
            time.sleep(2 * (i + 1))

def load_raw(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p): return pd.DataFrame(columns=["date", "code", "shares", "nav"])
    return pd.read_csv(p, dtype={"code": str})

def save_raw(df, name):
    df = df.drop_duplicates(["date", "code"], keep="last").sort_values(["code", "date"])
    df.to_csv(os.path.join(DATA, name), index=False)
    return df

# ---------------- A股 ----------------
def cn_codes():
    return sorted({c for v in CFG["cn"].values() for c in v})

def sse_day(d):
    r = get("https://query.sse.com.cn/commonQuery.do", headers={"Referer": "https://www.sse.com.cn/"}, params={
        "isPagination": "true", "pageHelp.pageSize": "10000", "pageHelp.pageNo": "1", "pageHelp.beginPage": "1",
        "pageHelp.cacheSize": "1", "pageHelp.endPage": "1",
        "sqlId": "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L", "STAT_DATE": d})
    return {x["SEC_CODE"]: float(x["TOT_VOL"]) * 1e4 for x in r.json()["result"]}

def szse_range(code, start, end):
    out, p = {}, 1
    while True:
        j = get("https://www.szse.cn/api/report/ShowReport/data", headers={"Referer": "https://www.szse.cn/market/fund/volume/etf/index.html"},
                params={"SHOWTYPE": "JSON", "CATALOGID": "scsj_fund_jjgm", "jjlb": "ETF", "txtDm": code,
                        "txtStart": start, "txtEnd": end, "PAGENO": p}).json()[0]
        for x in j["data"]:
            out[x["size_date"]] = float(x["current_size"].replace(",", "")) * 1e4
        if p >= (j["metadata"].get("pagecount") or 1): break
        p += 1; time.sleep(0.4)
    return out

def em_nav(code, start):
    out, p = {}, 1
    while True:
        j = get("https://api.fund.eastmoney.com/f10/lsjz", headers={"Referer": "https://fundf10.eastmoney.com/"},
                params={"fundCode": code, "pageIndex": p, "pageSize": 20, "startDate": start,
                        "endDate": dt.date.today().isoformat()}).json()
        L = (j.get("Data") or {}).get("LSJZList") or []
        for x in L:
            if x["DWJZ"]: out[x["FSRQ"]] = float(x["DWJZ"])
        if len(L) < 20 or p * 20 >= (j.get("TotalCount") or 0): break
        p += 1; time.sleep(0.25)
    return out

def update_cn():
    raw = load_raw("raw_cn.csv")
    codes = cn_codes()
    sh = [c for c in codes if c[0] in "5"]; sz = [c for c in codes if c[0] in "1"]
    today = dt.date.today()
    start = (raw["date"].max() if len(raw) else (today - dt.timedelta(days=DAYS)).isoformat())
    start_d = dt.date.fromisoformat(start) - dt.timedelta(days=7)   # 回看一周，覆盖修订
    shares = {}
    # 上交所：逐日
    d = start_d
    while d <= today:
        if d.weekday() < 5:
            try:
                m = sse_day(d.isoformat())
                for c in sh:
                    if c in m: shares[(d.isoformat(), c)] = m[c]
            except Exception as e:
                print("SSE fail", d, e)
            time.sleep(0.3)
        d += dt.timedelta(days=1)
    # 深交所：按代码、每段≤150天
    for c in sz:
        a = start_d
        while a <= today:
            b = min(a + dt.timedelta(days=150), today)
            try:
                for k, v in szse_range(c, a.isoformat(), b.isoformat()).items(): shares[(k, c)] = v
            except Exception as e:
                print("SZSE fail", c, a, e)
            a = b + dt.timedelta(days=1); time.sleep(0.5)
    navs = {}
    for c in codes:
        try:
            for k, v in em_nav(c, start_d.isoformat()).items(): navs[(k, c)] = v
        except Exception as e:
            print("NAV fail", c, e)
    rows = [{"date": k[0], "code": k[1], "shares": v, "nav": navs.get(k)} for k, v in shares.items()]
    new = pd.DataFrame(rows)
    df = pd.concat([raw, new]) if len(raw) else new
    return save_raw(df, "raw_cn.csv")

# ---------------- 美股 ----------------
def ssga(t):
    r = get(f"https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/navhist-us-en-{t.lower()}.xlsx")
    x = pd.read_excel(io.BytesIO(r.content), header=3).iloc[:, :3]
    x.columns = ["date", "nav", "shares"]
    x = x.dropna()
    x["date"] = pd.to_datetime(x["date"], format="%d-%b-%Y", errors="coerce").dt.date.astype(str)
    return x.dropna()

def vaneck(t):
    page = f"https://www.vaneck.com/us/en/investments/semiconductor-etf-{t.lower()}/overview/"
    get(page)  # 先拿 cookie
    r = get(f"https://www.vaneck.com/us/en/investments/semiconductor-etf-{t.lower()}/downloads/fundhistoprices/", headers={"Referer": page})
    x = pd.read_excel(io.BytesIO(r.content), header=1)
    x = x[["Date", "NAV", "AUM", "Volume"]].dropna(subset=["NAV", "AUM"])
    x = x[x["Volume"].notna()]                      # 去掉周末重复行
    x["date"] = pd.to_datetime(x["Date"], format="%m/%d/%Y", errors="coerce").dt.date.astype(str)
    x["nav"] = pd.to_numeric(x["NAV"], errors="coerce")
    x["shares"] = pd.to_numeric(x["AUM"].astype(str).str.replace(",", ""), errors="coerce") / x["nav"]
    x["shares"] = x["shares"].round(-3)             # AUM/NAV 反推，取整到千份
    return x[["date", "nav", "shares"]].dropna()

def update_us():
    cut = (dt.date.today() - dt.timedelta(days=DAYS + 10)).isoformat()
    parts = []
    for t in sorted({c for v in CFG["us"].values() for c in v}):
        try:
            x = vaneck(t) if t == "SMH" else ssga(t)
            x = x[x["date"] >= cut].copy(); x["code"] = t; parts.append(x)
        except Exception as e:
            print("US fail", t, e)
        time.sleep(0.5)
    df = pd.concat(parts)[["date", "code", "shares", "nav"]]
    raw = load_raw("raw_us.csv")
    return save_raw(pd.concat([raw, df]) if len(raw) else df, "raw_us.csv")

# ---------------- 计算 ----------------
def flows(df, market):
    df = df.dropna(subset=["shares"]).sort_values(["code", "date"]).copy()
    df["nav"] = df.groupby("code")["nav"].transform(lambda s: s.ffill())
    prev_sh = df.groupby("code")["shares"].shift()
    df["pnav"] = df.groupby("code")["nav"].shift()
    ratio = df["shares"] / prev_sh
    navr = df["nav"] / df["pnav"]
    df["split"] = (((ratio > 1.3) | (ratio < 0.77)) & ((ratio * navr - 1).abs() < 0.1)).fillna(False)
    df["split_kind"] = ratio.apply(lambda r: "split" if r > 1 else "merge")
    df["flow"] = (df["shares"] - prev_sh) * df["nav"]          # 原值：元 / 美元
    df.loc[df["split"], "flow"] = float("nan")
    df["aum"] = df["shares"] * df["nav"]
    df["pct"] = (navr - 1) * 100
    return df[prev_sh.notna()]

SECTOR_EN = {
    "半导体": "Semiconductors", "证券": "Brokerages", "银行": "Banks", "医药": "Pharmaceuticals",
    "新能源": "New Energy", "军工": "Defense", "AI/计算机": "AI & Computing", "消费/白酒": "Consumer",
    "有色/煤炭": "Metals & Coal",
    "科技 XLK": "Technology", "金融 XLF": "Financials", "医疗 XLV": "Health Care", "能源 XLE": "Energy",
    "工业 XLI": "Industrials", "可选消费 XLY": "Consumer Discretionary", "必选消费 XLP": "Consumer Staples",
    "公用事业 XLU": "Utilities", "材料 XLB": "Materials", "房地产 XLRE": "Real Estate",
    "通信 XLC": "Communication Services", "半导体 SMH": "Semiconductors",
}
SOURCE_NOTE = {
    "cn": "Shares: SSE / SZSE daily ETF scale reports (T-day close). NAV: Eastmoney. Net inflow = (shares_T - shares_T-1) x NAV_T. Self-calculated estimate.",
    "us": "Shares & NAV: issuer daily files (State Street SSGA; VanEck for SMH, shares = AUM / NAV). Net inflow = (shares_T - shares_T-1) x NAV_T. Self-calculated estimate.",
}

def num(v, nd=2):
    if v is None or (isinstance(v, float) and (v != v)): return None
    return round(float(v), nd)

def build(df, market, unit=None, scale=None):
    from zoneinfo import ZoneInfo
    groups = CFG[market]
    code2g = {c: g for g, cs in groups.items() for c in cs}
    df = df[df["code"].isin(code2g)].copy(); df["g"] = df["code"].map(code2g)
    cnt = df.groupby("date")["code"].nunique()
    need = int(0.8 * len(code2g))
    dates = sorted(cnt[cnt >= need].index)[-250:]
    df = df[df["date"].isin(dates)]
    flow_e = df.pivot_table(index="date", columns="code", values="flow", aggfunc="sum").reindex(dates)
    split_e = df.pivot_table(index="date", columns="code", values="split", aggfunc="max").reindex(dates)
    present = df.pivot_table(index="date", columns="g", values="code", aggfunc="count").reindex(dates)
    gs = list(groups.keys())
    sec = {}
    for g in gs:
        cs = [c for c in groups[g] if c in flow_e.columns]
        v = flow_e[cs].sum(axis=1, min_count=1)          # 拆分日(null)不计入
        if g in present.columns: v[present[g].isna()] = float("nan")
        else: v[:] = float("nan")
        sec[g] = v
    last = dates[-1]
    latest = df[df["date"] == last].set_index("code")
    names = NAMES.get(market, {})
    sectors, total = [], 0.0
    for g in gs:
        hist = sec[g].dropna()
        today = num(sec[g].iloc[-1])
        sig = None
        if len(hist) >= 60 and today is not None:
            sig = bool(abs(today) > hist.abs().quantile(0.95))
        etfs = []
        for c in groups[g]:
            if c not in latest.index: continue
            r = latest.loc[c]
            e = {"code": c, "name": names.get(c, c), "shares": int(round(r["shares"])),
                 "aum": num(r["aum"]), "net_inflow_today": None if r["split"] else num(r["flow"]),
                 "change_pct": num(r["pct"])}
            if r["split"]: e["corporate_action"] = r["split_kind"]
            etfs.append(e)
        etfs.sort(key=lambda e: -(e["aum"] or 0))
        total += today or 0.0
        sectors.append({"name": SECTOR_EN.get(g, g), "name_zh": g, "net_inflow_today": today, "signal_95": sig, "etfs": etfs})
    def ser(v): return [None if x != x else round(float(x), 2) for x in v.tolist()]
    out = {
        "schema_version": 1,
        "market": market.upper(),
        "currency": "CNY" if market == "cn" else "USD",
        "units": {"money": "CNY" if market == "cn" else "USD", "shares": "shares"},
        "data_date": last,
        "updated_at": dt.datetime.now(ZoneInfo("America/Edmonton")).replace(microsecond=0).isoformat(),
        "total_net_inflow": round(total, 2),
        "sectors": sectors,
        "history": {
            "dates": dates,
            "daily_by_sector": {SECTOR_EN.get(g, g): ser(sec[g]) for g in gs},
            "daily_by_etf": {c: ser(flow_e[c]) if c in flow_e.columns else [None] * len(dates) for c in code2g},
        },
        "source_note": SOURCE_NOTE[market],
    }
    # 校验后原子写入：失败时保留上一份
    assert len(sectors) == len(gs) and dates and all(len(v) == len(dates) for v in out["history"]["daily_by_sector"].values())
    assert abs(out["total_net_inflow"] - sum(s["net_inflow_today"] or 0 for s in sectors)) < 1
    path = os.path.join(DATA, f"{market}.json"); tmp = path + ".tmp"
    json.dump(out, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    os.replace(tmp, path)
    print(market, "data_date", last, "history from", dates[0], "days", len(dates))

def cn_names():
    p = os.path.join(DATA, "names_cn.json")
    if os.path.exists(p): return json.load(open(p, encoding="utf-8"))
    names = {}
    try:
        d = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        r = get("https://query.sse.com.cn/commonQuery.do", headers={"Referer": "https://www.sse.com.cn/"}, params={
            "isPagination": "true", "pageHelp.pageSize": "10000", "pageHelp.pageNo": "1", "pageHelp.beginPage": "1",
            "pageHelp.cacheSize": "1", "pageHelp.endPage": "1", "sqlId": "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L", "STAT_DATE": ""})
        names.update({x["SEC_CODE"]: x["SEC_NAME"] for x in r.json()["result"]})
    except Exception:
        pass
    names = {c: names.get(c, c) for c in cn_codes()}
    json.dump(names, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    return names

US_NAMES = {"XLK": "Technology Select Sector SPDR", "XLF": "Financial Select Sector SPDR", "XLV": "Health Care Select Sector SPDR",
            "XLE": "Energy Select Sector SPDR", "XLI": "Industrial Select Sector SPDR", "XLY": "Consumer Discretionary Select Sector SPDR",
            "XLP": "Consumer Staples Select Sector SPDR", "XLU": "Utilities Select Sector SPDR", "XLB": "Materials Select Sector SPDR",
            "XLRE": "Real Estate Select Sector SPDR", "XLC": "Communication Services Select Sector SPDR", "SMH": "VanEck Semiconductor ETF"}

if __name__ == "__main__":
    os.makedirs(DATA, exist_ok=True)
    args = sys.argv[1:]
    only = next((a for a in args if a in ("cn", "us")), None)
    build_only = "--build-only" in args
    NAMES = {"us": US_NAMES}
    failed = False
    for m in ("cn", "us"):
        if only and m != only: continue
        try:
            if m == "cn": NAMES["cn"] = cn_names()
            raw = load_raw(f"raw_{m}.csv") if build_only else (update_cn() if m == "cn" else update_us())
            build(flows(raw, m), m)
        except Exception as e:           # 失败时保留上一份 JSON
            failed = True; print("FAILED", m, repr(e))
    sys.exit(1 if failed else 0)
