# KoinScan — multichain.py
# Analisa multi-chain (Ethereum, BSC, Base, TON, Arbitrum, Polygon, dll) sebagai tambahan
# di atas fokus utama Solana.
#
# Sumber:
#   1. DexScreener search per jaringan (bebas rate-limit ketat, cepat) — sumber utama
#   2. GeckoTerminal trending per network (30 call/menit gratis; dipakai hemat + cache 10 mnt)
#   3. Arkham Intelligence: API resmi butuh API key gratis (x-api-key).
#      Kalau env ARKHAM_API_KEY diisi, sumber on-chain flow Arkham ikut dipakai.
#
# Stdlib only. Cache in-memory supaya hemat kuota.
import json, os, time, urllib.request, urllib.parse

DS = "https://api.dexscreener.com/latest/dex"
GT = "https://api.geckoterminal.com/api/v2"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
      "Accept": "application/json"}

_cache = {}

def _cget(k, ttl):
    v = _cache.get(k)
    return v[1] if v and time.time() - v[0] < ttl else None

def _cset(k, v):
    _cache[k] = (time.time(), v)

def _get(url, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())

def _num(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0

CHAIN_LABEL = {
    "ethereum": "Ethereum", "bsc": "BSC", "base": "Base", "ton": "TON",
    "arbitrum": "Arbitrum", "polygon_pos": "Polygon", "avax": "Avalanche",
    "pulsechain": "PulseChain", "robinhood": "Robinhood", "optimism": "Optimism",
    "solana": "Solana", "sui": "Sui", "tron": "Tron", "zksync": "zkSync",
    "blast": "Blast", "mantle": "Mantle", "linea": "Linea", "hyperliquid": "HyperEVM",
}

# Kueri per jaringan (kata kunci meme yang efektif di DexScreener search)
JARINGAN = [
    ("ethereum", "ethereum meme"),
    ("bsc", "bnb meme"),
    ("base", "base meme"),
    ("ton", "ton meme"),
    ("arbitrum", "arbitrum meme"),
    ("polygon_pos", "polygon meme"),
]


def _fmt_ds(p):
    """Normalisasi pair DexScreener → format koin KoinScan."""
    bt = p.get("baseToken") or {}
    chg = p.get("priceChange") or {}
    tx = p.get("txns") or {}
    h1 = tx.get("h1") or {}
    liq = _num((p.get("liquidity") or {}).get("usd"))
    mc = _num(p.get("marketCap")) or _num(p.get("fdv"))
    buys, sells = _num(h1.get("buys")), _num(h1.get("sells"))
    chain = p.get("chainId", "?")
    return {
        "simbol": bt.get("symbol", "?")[:16],
        "nama": (bt.get("name") or "?")[:20],
        "mint": bt.get("address", ""),
        "sumber": "multichain",
        "chain": chain,
        "pool": (pr.get("pairAddress") or ""),
        "chain_label": CHAIN_LABEL.get(chain, chain.upper()),
        "dex": p.get("dexId", "?"),
        "img": (bt.get("logoURI") or "").strip(),
        "mc": mc,
        "liq": liq,
        "h1": _num(chg.get("h1")),
        "h24": _num(chg.get("h24")),
        "vol24": _num((p.get("volume") or {}).get("h24")),
        "tekanan_beli": round(buys / (buys + sells) * 100) if (buys + sells) else 50,
        "harga": _num(p.get("priceUsd")),
        "url": p.get("url", ""),
    }


def skor_mc(k):
    """Skor 0-100 utk koin multi-chain (logika skor_dex + filter likuiditas)."""
    s = 0.0
    mc, liq = k.get("mc") or 0, k.get("liq") or 0
    if 50_000 <= mc <= 20_000_000: s += 25
    elif mc > 20_000_000: s += 12
    r = liq / mc if mc else 0
    if r >= 0.1: s += 20
    elif r >= 0.04: s += 12
    vol = k.get("vol24") or 0
    if mc and vol / mc >= 1: s += 20
    elif mc and vol / mc >= 0.3: s += 12
    h1 = k.get("h1") or 0
    if h1 >= 10: s += 15
    elif h1 >= 3: s += 8
    tb = k.get("tekanan_beli") or 0
    if tb >= 60: s += 15
    elif tb >= 50: s += 8
    if (k.get("h24") or 0) >= 50: s += 10
    return round(max(0, min(100, s)), 1)


def _ds_multichain():
    """DexScreener: kumpulkan pair meme per jaringan (bukan Solana)."""
    out = {}
    for net, q in JARINGAN:
        try:
            d = _get(f"{DS}/search?q={urllib.parse.quote(q)}")
            for p in (d.get("pairs") or []):
                if p.get("chainId") != net:
                    continue
                k = _fmt_ds(p)
                if not k["simbol"] or k["simbol"] == "?" or k["liq"] < 20_000:
                    continue
                m = k["mint"]
                if m and (m not in out or k["liq"] > out[m]["liq"]):
                    out[m] = k
        except Exception:
            pass
        time.sleep(0.5)
    return list(out.values())


def _gt_multichain():
    """GeckoTerminal trending per network (hemat kuota: cache 10 menit)."""
    hit = _cget("gt_mc", 600)
    if hit is not None:
        return hit
    out = []
    for net, _q in JARINGAN[:4]:  # 4 call per refresh — aman kuota
        try:
            d = _get(f"{GT}/networks/{net}/trending_pools?page=1")
            for p in (d.get("data") or []):
                a = p.get("attributes") or {}
                rel = ((p.get("relationships") or {}).get("base_token") or {}).get("data") or {}
                tok_id = rel.get("id") or ""
                # ambil nama koin dari nama pool "XXX / WETH"
                nm = (a.get("name") or "?").split("/")[0].strip()
                chg = a.get("price_change_percentage", {}) or {}
                vol = a.get("volume_usd", {}) or {}
                tx = (a.get("transactions") or {}).get("h24", {}) or {}
                buys, sells = _num(tx.get("buys")), _num(tx.get("sells"))
                out.append({
                    "simbol": nm[:16],
                    "nama": nm[:20],
                    "mint": tok_id,
                    "sumber": "multichain-gt",
                    "chain": net,
                    "chain_label": CHAIN_LABEL.get(net, net.upper()),
                    "img": "",
                    "mc": _num(a.get("market_cap_usd")) or _num(a.get("fdv_usd")),
                    "liq": _num(a.get("reserve_in_usd")),
                    "h1": _num(chg.get("h1")),
                    "h24": _num(chg.get("h24")),
                    "vol24": _num(vol.get("h24")),
                    "tekanan_beli": round(buys / max(1, buys + sells) * 100),
                    "url": f"https://www.geckoterminal.com/{net}/pools/{a.get('address','')}",
                })
        except Exception:
            pass
        time.sleep(2.2)  # GT gratis ±30 call/menit — jeda aman
    _cset("gt_mc", out)
    return out


def _arkham_trending():
    """Arkham Intelligence (OPSIONAL): aktif bila env ARKHAM_API_KEY tersedia.
    API: https://api.arkhamintelligence.com/... header x-api-key. Tanpa key → kosong."""
    key = os.environ.get("ARKHAM_API_KEY") or ""
    if not key:
        return []
    try:
        req = urllib.request.Request(
            "https://api.arkhamintelligence.com/tokens/trending?timeframe=24h",
            headers={**UA, "x-api-key": key})
        d = json.loads(urllib.request.urlopen(req, timeout=15).read())
        out = []
        for t in (d if isinstance(d, list) else d.get("tokens") or []):
            out.append({
                "simbol": (t.get("symbol") or "?")[:16],
                "nama": (t.get("name") or "?")[:20],
                "mint": t.get("address") or t.get("contractAddress") or "",
                "sumber": "arkham",
                "chain": t.get("chain") or "?",
                "chain_label": CHAIN_LABEL.get(t.get("chain") or "", (t.get("chain") or "?").upper()),
                "img": (t.get("logo") or "").strip(),
                "mc": _num(t.get("marketCap")),
                "liq": _num(t.get("liquidity")),
                "h1": _num(t.get("priceChange1h")),
                "h24": _num(t.get("priceChange24h")),
                "vol24": _num(t.get("volume24h")),
                "tekanan_beli": None,
                "url": "",
            })
        return out
    except Exception:
        return []


def papan_multichain(batas=50):
    """Papan koin multi-chain gabungan (dedupe, sort skor)."""
    hit = _cget("mc_papan", 120)
    if hit is not None:
        return hit
    gabung = {}
    for k in _ds_multichain() + _gt_multichain() + _arkham_trending():
        m = k.get("mint")
        if not m:
            continue
        if m in gabung:
            # merge: isi img yang kosong
            if not gabung[m].get("img") and k.get("img"):
                gabung[m]["img"] = k["img"]
            continue
        k["skor"] = skor_mc(k)
        gabung[m] = k
    papan = sorted(gabung.values(), key=lambda x: -(x.get("skor") or 0))[:batas]
    out = {"ts": time.time(),
           "waktu": time.strftime("%Y-%m-%d %H:%M:%S"),
           "total": len(papan), "koin": papan,
           "catatan": "Sumber: DexScreener + GeckoTerminal" +
                      (" + Arkham" if os.environ.get("ARKHAM_API_KEY") else "") +
                      " — Arkham aktif otomatis bila ARKHAM_API_KEY diset"}
    _cset("mc_papan", out)
    return out


if __name__ == "__main__":
    p = papan_multichain()
    print("total:", p["total"], "|", p["catatan"])
    from collections import Counter
    print(Counter(k["chain_label"] for k in p["koin"]).most_common())
    for k in p["koin"][:8]:
        print(f" {k['simbol']:10} {k['chain_label']:10} skor {k['skor']:5} MC ${k['mc']:,.0f} 1j {k['h1']:+.1f}%")
