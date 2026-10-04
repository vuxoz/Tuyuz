# KoinScan Solana — scanner meme coin SOL real-time (pump.fun + pumpswap + DEX Solana lain)
# Mandiri, stdlib only.
# Sumber:
#   1. pump.fun frontier v3  → koin baru (bonding curve) + top MC
#   2. DexScreener batch     → koin graduated (pumpswap/raydium/orca/meteora) = koin "stonk"
#   3. GeckoTerminal solana  → trending pools lintas DEX Solana (alternatif meme lain)
import json
import urllib.request, os, time, math, threading, urllib.request, urllib.error

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
os.makedirs(DATA, exist_ok=True)
CACHE = os.path.join(DATA, "scan.json")

PUMP = "https://frontend-api-v3.pump.fun"
DS = "https://api.dexscreener.com/latest/dex"
GT = "https://api.geckoterminal.com/api/v2"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _get(url, retries=3):
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            return json.loads(urllib.request.urlopen(req, timeout=20).read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < retries:
                time.sleep(15)
                continue
            raise
        except Exception:
            if i < retries:
                time.sleep(3)
                continue
            raise


def _num(x, d=0):
    try:
        v = float(x)
        return v if v == v else d
    except (TypeError, ValueError):
        return d


def _f(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


# ---------- PUMP.FUN ----------
def pump_ambil(sort, limit=30, retries=3):
    """sort: created_timestamp (baru) | market_cap (top). Retry 429 dengan jeda panjang."""
    for i in range(retries + 1):
        try:
            return _get(f"{PUMP}/coins?sort={sort}&order=DESC&limit={limit}")
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < retries:
                time.sleep(25)
                continue
            print("pump", sort, "err:", e)
            return []
        except Exception as e:
            if i < retries:
                time.sleep(10)
                continue
            print("pump", sort, "err:", e)
            return []


def pump_fmt(c):
    """Koin di bonding curve (belum graduated)."""
    usd_mc = _num(c.get("usd_market_cap"))
    created = _num(c.get("created_timestamp")) / 1000
    umur_jam = (time.time() - created) / 3600 if created else None
    return {
        "simbol": c.get("symbol", "?"),
        "nama": (c.get("name") or "?")[:20],
        "sumber": "pumpfun",
        "mint": c.get("mint", ""),
        "img": (c.get("image_uri") or "").strip(),
        "metadata_uri": (c.get("metadata_uri") or "").strip(),
        "mc": usd_mc,
        "complete": bool(c.get("complete")),
        "umur_jam": round(umur_jam, 1) if umur_jam is not None else None,
        "replies": _num(c.get("reply_count")),
        "live": bool(c.get("is_currently_live")),
        "url": f"https://pump.fun/coin/{c.get('mint','')}",
    }


# ---------- DEXSCREENER (graduated / pumpswap / raydium dll) ----------


def simpan_proyek_dari_pump(coins):
    """Simpan deskripsi proyek + sosial dari respons list pump.fun → data/proyek_map.json"""
    try:
        import proyek
        m = proyek._muat()
        n = 0
        for c in coins:
            mint = c.get("mint") or ""
            desc = (c.get("description") or "").strip()
            tw = (c.get("twitter") or "").strip()
            tg = (c.get("telegram") or "").strip()
            ws = (c.get("website") or "").strip()
            if not (desc or tw or tg or ws) or not mint:
                continue
            lama = m.get(mint)
            if lama and (lama.get("deskripsi") or lama.get("twitter")):
                continue  # sudah ada data lebih lengkap
            m[mint] = {"mint": mint, "deskripsi": desc[:500], "website": ws,
                       "twitter": tw, "telegram": tg, "banner": "", "ts": time.time()}
            n += 1
        if n:
            proyek._simpan(m)
    except Exception:
        pass


def ds_graduated(mints):
    """Batch cek koin pump.fun yang complete → pair DEX (loop batch @30 mint)."""
    out = []
    mints = [m for m in mints if m]
    for i in range(0, len(mints), 30):
        batch = mints[i:i+30]
        try:
            d = _get(f"{DS}/tokens/{','.join(batch)}")
            out.extend(d.get("pairs") or [])
        except Exception as e:
            print("ds err:", e)
        time.sleep(0.4)
    return out


def ds_fmt(p):
    tok = p.get("baseToken", {})
    liq = _num((p.get("liquidity") or {}).get("usd"))
    mc = _num(p.get("marketCap")) or _num(p.get("fdv"))
    pc = p.get("priceChange", {}) or {}
    vol = p.get("volume", {}) or {}
    tx = (p.get("txns") or {}).get("h24", {}) or {}
    buys, sells = _num(tx.get("buys")), _num(tx.get("sells"))
    tot = buys + sells
    info = p.get("info") or {}
    return {
        "simbol": tok.get("symbol", "?"),
        "nama": (tok.get("name") or "?")[:20],
        "sumber": p.get("dexId", "dex"),
        "mint": tok.get("address", ""),
        "img": (info.get("imageUrl") or "").strip(),
        "mc": mc,
        "liq": liq,
        "h1": _f(pc.get("h1")),
        "h24": _f(pc.get("h24")),
        "vol24": _num(vol.get("h24")),
        "tekanan_beli": round(buys / tot * 100) if tot else 50,
        "url": p.get("url") or "",
    }


# ---------- GECKOTERMINAL (trending solana, semua DEX) ----------
def gt_trending():
    try:
        d = _get(f"{GT}/networks/solana/trending_pools?include=base_token,dex&page=1")
        tokens = {a["id"]: a.get("attributes", {}) for a in d.get("included", [])
                  if a.get("type") == "token"}
        out = []
        for p in d.get("data", []):
            attr = p.get("attributes", {})
            rel = p.get("relationships", {})
            tok = tokens.get((rel.get("base_token") or {}).get("data", {}).get("id"), {})
            out.append((attr, tok))
        return out
    except Exception as e:
        print("gt err:", e)
        return []


# Logo koin DEX: DexScreener punya imageUrl — ambil on-demand & cache file
LOGO_DIR = os.path.join(DATA, "logo")
LOGO_MAP = os.path.join(DATA, "logo_map.json")


def logo_untuk(mint):
    """URL logo koin: 1) cache map, 2) DexScreener info.imageUrl (batch)."""
    try:
        mp = _load_json(LOGO_MAP)
        if mint in mp:
            return mp[mint]
    except Exception:
        mp = {}
    return mp.get(mint)


def _load_json(path):
    with open(path) as f:
        return json.load(f)


def simpan_logo_map(mints):
    """Batch isi logo_map.json dari DexScreener (1 call / 30 mint)."""
    mints = [m for m in mints if m]
    if not mints:
        return
    try:
        mp = _load_json(LOGO_MAP)
    except Exception:
        mp = {}
    baru = [m for m in mints if m not in mp]
    if not baru:
        return
    # DS batch = 30 mint/call; batasi 4 call agar tidak membebani API
    for i in range(0, min(len(baru), 120), 30):
        try:
            d = _get(f"{DS}/tokens/{','.join(baru[i:i+30])}")
            for p in (d.get("pairs") or []):
                m = (p.get("baseToken") or {}).get("address")
                u = ((p.get("info") or {}).get("imageUrl") or "").strip()
                if m and u and m not in mp:
                    mp[m] = u
        except Exception as e:
            print("logo err:", e)
    try:
        with open(LOGO_MAP, "w") as f:
            json.dump(mp, f)
    except Exception as e:
        print("logo save err:", e)


def gt_fmt(attr, tok):
    pc = attr.get("price_change_percentage", {}) or {}
    vol = attr.get("volume_usd", {}) or {}
    tx = (attr.get("transactions") or {}).get("h24", {}) or {}
    buys, sells = _num(tx.get("buys")), _num(tx.get("sells"))
    tot = buys + sells
    return {
        "simbol": tok.get("symbol", "?"),
        "nama": (tok.get("name") or "?")[:20],
        "sumber": "solana-dex",
        "mint": tok.get("address", ""),
        "img": (tok.get("image_url") or "") if isinstance(tok, dict) else "",
        "mc": _num(attr.get("market_cap_usd")) or _num(attr.get("fdv_usd")),
        "liq": _num(attr.get("reserve_in_usd")),
        "h1": _f(pc.get("h1")),
        "h24": _f(pc.get("h24")),
        "vol24": _num(vol.get("h24")),
        "tekanan_beli": round(buys / tot * 100) if tot else 50,
        "url": f"https://www.geckoterminal.com/solana/pools/{attr.get('address','')}",
    }


# ---------- SKOR ----------
def skor_dex(liq, h1, h24, vol, mc, tekanan):
    s = 0.0
    s += min(25, max(0, (math.log10(liq + 1) - 4) / 2 * 25))
    if h1 is not None:
        s += min(20, max(0, h1) / 5 * 20)
    if h24 is not None:
        s += min(15, max(0, h24) / 50 * 15)
    s += min(20, ((vol / liq) if liq else 0) / 5 * 20)
    s += min(10, tekanan / 100 * 10)
    if h24 is not None and h24 < 0:
        s += max(-25, h24 / 4)  # dump 24j = penalti hingga -25
    if mc > 500_000_000:
        s -= 10
    return round(max(0, min(100, s)), 1)


def skor_pump(k):
    """Koin bonding curve: berbasis MC, umur, aktivitas sosial, kelulusan mendekat."""
    s = 0.0
    mc = k["mc"]
    if 30_000 <= mc <= 500_000:
        s += 30
    elif 5_000 <= mc < 30_000:
        s += 20
    elif 500_000 < mc <= 2_000_000:
        s += 15
    u = k.get("umur_jam")
    if u is not None:
        s += 20 if u < 6 else 12 if u < 24 else 5 if u < 72 else 0
    s += min(15, k.get("replies", 0) / 10 * 15)
    s += 10 if k.get("live") else 0
    if k.get("complete"):
        s += 15
    elif 50_000 <= mc < 69_000:
        s += 12
    return round(max(0, min(100, s)), 1)




def raydium_ambil(batas=60):
    """Koin di pool Raydium (CLMM/Cpmm/AMM) dgn TVL kecil-menengah = koin 'muda' di DEX raydium.
    Sumber: api-v3.raydium.io pools info/list. Koin biru & stablecoin dibuang."""
    try:
        d = _get("https://api-v3.raydium.io/pools/info/list?poolType=all&poolSortField=volume24h&sortType=desc&pageSize=100&page=1")
        pools = (d.get("data") or {}).get("data") or []
    except Exception:
        return []
    biru = {"So11111111111111111111111111111111111111112",
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
            "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So"}
    populer = {"WSOL","USDC","USDT","MSOL","JUP","BONK","SOL","RAY","PUMP","FARTCOIN","STONK"}
    out, lihat = [], set()
    for p in pools:
        tvl = _num(p.get("tvl") or 0)
        if tvl < 5000 or tvl > 5_000_000:   # fokus koin kecil-menengah, bukan pool institusi
            continue
        day = p.get("day") or {}
        for side in ("mintA", "mintB"):
            m = p.get(side) or {}
            mint = m.get("address") or ""
            sim = (m.get("symbol") or "?").strip()
            if mint in biru or sim.upper() in populer or mint in lihat:
                continue
            lihat.add(mint)
            out.append({
                "simbol": sim[:16],
                "nama": (m.get("name") or sim)[:20],
                "mint": mint,
                "sumber": "raydium",
                "url": "https://dexscreener.com/solana/" + mint,
                "img": m.get("logoURI") or "",
                "harga": _num(p.get("price") or 0),
                "mc": 0, "liq": tvl,
                "h1": _num((p.get("hour") or {}).get("priceChange") or 0),
                "h24": _num(day.get("priceChange") or 0),
                "vol24": _num(day.get("volume") or 0),
                "tekanan_beli": 50,
            })
            if len(out) >= batas:
                return out
    return out




def gmgn_ambil(batas=40):
    """Koin aktif Solana dari GMGN (rank swaps 1h) — data risiko emas:
    bundler_rate, rug_ratio, holder_count, smart_degen_count."""
    H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
         "Accept": "application/json",
         "Referer": "https://gmgn.ai/sol/tokenrank"}
    try:
        req = urllib.request.Request(
            "https://gmgn.ai/defi/quotation/v1/rank/sol/swaps/1h?orderby=swaps&direction=desc&limit=60",
            headers=H)
        d = json.loads(urllib.request.urlopen(req, timeout=20).read())
        rank = (d.get("data") or {}).get("rank") or []
    except Exception:
        return []
    out = []
    now = time.time()
    for t in rank:
        mint = t.get("address") or ""
        sim = (t.get("symbol") or "?").strip()
        if not mint or sim == "?":
            continue
        umur_j = (now - (t.get("creation_timestamp") or now)) / 3600 if t.get("creation_timestamp") else 999
        if umur_j > 168:   # fokus koin muda ≤7 hari
            continue
        rug = t.get("rug_ratio") or 0
        bundler = t.get("bundler_rate") or 0
        holders = t.get("holder_count") or 0
        liq = _num(t.get("liquidity") or 0)
        # skor: likes = swap + holder; risiko dari bundler/rug/holder sedikit
        skor = 40 + min(20, holders / 100) + min(10, liq / 20000) - bundler * 100 - rug * 30
        out.append({
            "simbol": sim[:16],
            "nama": (t.get("name") or sim)[:20],
            "mint": mint,
            "sumber": "gmgn",
            "url": "https://dexscreener.com/solana/" + mint,
            "img": (t.get("logo") or "").strip(),
            "harga": 0,
            "mc": _num(t.get("market_cap") or 0),
            "liq": liq,
            "h1": 0,
            "h24": _num(t.get("price_change_percent") or 0) / 100.0,
            "vol24": _num(t.get("swaps") or 0),
            "tekanan_beli": round((t.get("buys") or 0) / max(1, (t.get("swaps") or 1)) * 100),
            "skor": max(5, round(skor)),
            "flag": (["BUNDLER"] if bundler > 0.1 else []) + (["RUG-RISIKO"] if rug > 0.5 else []),
            "holder_count": holders,
        })
        if len(out) >= batas:
            break
    return out


def _pindai_bg():
    threading.Thread(target=lambda: pindai(force=True), daemon=True).start()


def pindai(force=False):
    if not force:
        try:
            with open(CACHE) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _pindai_bg()
            return {}

    # --- 1. pump.fun bonding curve ---
    pump_map = {}
    for c in pump_ambil("created_timestamp", 100):
        if c.get("mint") and c["mint"] not in pump_map:
            pump_map[c["mint"]] = c
    time.sleep(3)  # pump.fun rate-limit: jeda antar-panggilan
    for c in pump_ambil("market_cap", 100):
        if c.get("mint") and c["mint"] not in pump_map:
            pump_map[c["mint"]] = c
    time.sleep(3)
    # koin mendekati graduation (king of the hill) — calon stonk berikutnya
    for c in pump_ambil("reply_count", 100):
        if c.get("mint") and c["mint"] not in pump_map:
            pump_map[c["mint"]] = c

    # 📝 INFO PROYEK: simpan deskripsi + sosial dari respons pump.fun (tanpa request tambahan)
    simpan_proyek_dari_pump(list(pump_map.values()))

    # 📊 RISET PELACAKAN: simpan snapshot ke tracker + skor berbasis pertumbuhan riil
    import pump_riset
    pump_riset.lacak(list(pump_map.values()))
    pump_riset.catat_creator(list(pump_map.values()))

    koin_baru = []       # masih di bonding curve, umur ≤72 jam (definisi "koin baru")
    koin_stonk = []      # complete → perlu pair DEX
    now_ts = time.time()
    for c in pump_map.values():
        k = pump_fmt(c)
        if k["simbol"] == "?":
            continue
        if c.get("complete"):
            koin_stonk.append(k)
        else:
            umur_total_jam = (now_ts - (c.get("created_timestamp", 0) / 1000 or now_ts)) / 3600
            if umur_total_jam > 72:
                continue  # mandek lama di curve = bukan koin baru lagi
            # skor riset (pelacakan antar-poll); fallback skor statis utk koin baru terlihat
            tr = pump_riset._load(pump_riset.TRACK_FILE, {})
            ent = tr.get(c["mint"])
            if ent and ent.get("poll", 0) >= 2:
                k["skor"], k["riset_alasan"] = pump_riset.nilai(ent, pump_riset._load(pump_riset.CREATOR_FILE, {}))
                k["growth"] = round(ent["mc"] / (ent.get("mc_awal") or 1), 2)
                k["konsisten"] = ent.get("konsisten", 0)
                k["poll"] = ent.get("poll", 0)
                k["pegang_ath"] = round(ent["mc"] / ent["ath_mc"] * 100) if ent.get("ath_mc") else 0
            else:
                k["skor"] = skor_pump(k)
                k["riset_alasan"] = ["baru pertama terpantau — riset butuh 2 poll (±20 menit)"]
            koin_baru.append(k)

    # ⭐ tambahan: kandidat riset terbaik dari tracker (bisa lebih banyak dari feed sesaat)
    # standar berlapis: ≥40 = kandidat utama; ≥25 = pantauan (ditandai); <25 tidak tampil
    riset_layak = pump_riset.kandidat_layak(min_skor=25, min_poll=2)
    sudah = {k["mint"] for k in koin_baru}
    for r in riset_layak:
        if r["mint"] not in sudah:
            koin_baru.append(r)
            sudah.add(r["mint"])

    # --- 2. graduated → DexScreener untuk data pasar ---
    graduated = []
    ketemu = set()
    for p in ds_graduated([k["mint"] for k in koin_stonk if k["mint"]]):
        k = ds_fmt(p)
        if k["simbol"] == "?" or (k.get("liq") or 0) < 5_000:
            continue
        if k.get("mint") in ketemu:
            continue
        ketemu.add(k.get("mint"))
        k["skor"] = skor_dex(k["liq"], k["h1"], k["h24"], k["vol24"], k["mc"], k["tekanan_beli"])
        graduated.append(k)
    # koin complete yang tak ketemu pair DS (429 dsb) → tetap masuk pakai data pump.fun
    for k in koin_stonk:
        if k.get("mint") and k["mint"] not in ketemu:
            k2 = dict(k)
            k2.setdefault("sumber", "pumpfun-graduated")
            graduated.append(k2)
            ketemu.add(k["mint"])

    # --- 3. trending Solana lintas DEX (alternatif meme lain) ---
    alternatif = []
    for attr, tok in gt_trending():
        k = gt_fmt(attr, tok)
        if k["simbol"] == "?" or k["liq"] < 15_000:
            continue
        k["skor"] = skor_dex(k["liq"], k["h1"], k["h24"], k["vol24"], k["mc"], k["tekanan_beli"])
        alternatif.append(k)

    # --- 3b. koin di RAYDIUM (pool muda non-biru) — sumber tambahan koin baru DEX ---
    try:
        ray = raydium_ambil(40)
        mint_ray = {k["mint"] for k in alternatif} | {k["mint"] for k in graduated}
        for k in ray:
            if k["mint"] in mint_ray:
                continue
            k["skor"] = skor_dex(k["liq"], k["h1"], k["h24"], k["vol24"], k["mc"], k["tekanan_beli"])
            alternatif.append(k)
            mint_ray.add(k["mint"])
    except Exception:
        pass

    # --- 3c. koin aktif GMGN (data risiko: bundler/rug/holder) ---
    try:
        sudah_g = {k["mint"] for k in alternatif}
        for k in gmgn_ambil(40):
            if k["mint"] in sudah_g:
                continue
            alternatif.append(k)
            sudah_g.add(k["mint"])
    except Exception:
        pass

    def bersihkan(lst, n):
        seen, unik = set(), []
        for k in sorted(lst, key=lambda x: -x.get("skor", 0)):
            key = k.get("mint") or (k["simbol"], k["sumber"])
            if key in seen:
                continue
            seen.add(key)
            unik.append(k)
        return unik[:n]

    # ---------- 🔬 ANALISA RISIKO (honeypot/bundler/rug/scam) ----------
    # Periksa semua kandidat unik via RugCheck; koin SCAM/BAHAYA disingkirkan
    # dari "menarik dibeli" & masing-masing papan, tapi tetap ditampilkan di papan risiko.
    import risiko
    # Analisa per MINT (bukan per objek) — satu mint bisa jadi objek berbeda di beberapa list.
    risiko_by_mint = {}
    for k in (koin_baru + graduated + alternatif):
        mint = k.get("mint")
        if not mint or mint in risiko_by_mint:
            continue
        try:
            r = risiko.analisa_mint(mint)
            risiko_by_mint[mint] = r or {"putusan": "TIDAK-DIKETAHUI", "flag": [], "peringatan": []}
        except Exception as e:
            print("risiko err", k["simbol"], e)
            risiko_by_mint[mint] = {"putusan": "TIDAK-DIKETAHUI", "flag": [], "peringatan": []}
    # pasang risiko ke SEMUA objek
    for k in (koin_baru + graduated + alternatif):
        k["risiko"] = risiko_by_mint.get(k.get("mint")) or \
            {"putusan": "TIDAK-DIKETAHUI", "flag": [], "peringatan": []}

    def lolos_filter(k):
        return k.get("risiko", {}).get("putusan") not in ("SCAM", "BAHAYA")

    # 🖼️ logo/banner koin: isi dari DexScreener utk koin yang belum punya gambar
    semua_mint = [k.get("mint") for k in (koin_baru + graduated + alternatif)]
    try:
        simpan_logo_map(semua_mint)
        lmap = _load_json(LOGO_MAP)
    except Exception:
        lmap = {}
    for k in (koin_baru + graduated + alternatif):
        if not k.get("img"):
            k["img"] = lmap.get(k.get("mint") or "", "")
        k["logo"] = k.get("img") or ""

    aman_baru = [k for k in koin_baru if lolos_filter(k)]
    aman_grad = [k for k in graduated if lolos_filter(k)]
    aman_alt = [k for k in alternatif if lolos_filter(k)]
    terfilter_scam = sorted(
        [k for k in (koin_baru + graduated + alternatif) if not lolos_filter(k)],
        key=lambda x: -x.get("skor", 0))

    # ⭐ menarik dibeli: HANYA koin lolos analisa risiko, terurut skor
    menarik = bersihkan(aman_baru + aman_grad + aman_alt, 50)

    # akumulasi: tekanan beli dominan + momentum naik (hanya koin dgn data DEX)
    akumulasi = sorted(
        [k for k in (graduated + alternatif)
         if k.get("tekanan_beli", 0) >= 60 and (k.get("h1") or 0) > 0],
        key=lambda k: -(k["tekanan_beli"] + (k["h1"] or 0)))[:50]

    feed = {
        "ts": time.time(),
        "waktu": time.strftime("%Y-%m-%d %H:%M:%S"),
        "jaringan": "solana",
        "total_dipindai": len(koin_baru) + len(graduated) + len(alternatif),
        "menarik_dibeli": menarik,
        "pumpfun_baru": bersihkan(aman_baru, 50),
        "pumpfun_stonk": bersihkan(aman_grad, 50),
        "solana_alternatif": bersihkan(aman_alt, 50),
        "akumulasi": [k for k in akumulasi if lolos_filter(k)],
        "terfilter_scam": terfilter_scam[:50],
    }
    with open(CACHE, "w") as f:
        json.dump(feed, f, ensure_ascii=False)
    return feed


if __name__ == "__main__":
    f = pindai(force=True)
    print("dipindai:", f["total_dipindai"], "|", f["waktu"])
    for kat in ("menarik_dibeli", "pumpfun_baru", "pumpfun_stonk", "solana_alternatif", "akumulasi"):
        print(f"\n== {kat.upper()} ({len(f[kat])}) ==")
        for k in f[kat][:5]:
            ekstra = f"umur {k['umur_jam']}j" if k.get("umur_jam") is not None else f"24j {k.get('h24')}%"
            print(f"  {k['simbol']:<12} [{k['sumber']:<10}] skor {k.get('skor',0):>4} "
                  f"MC ${k['mc']:,.0f} {ekstra}")
