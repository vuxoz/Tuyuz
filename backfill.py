# KoinScan — pengisi riwayat grafik koin DEX (GeckoTerminal OHLCV).
#
# Masalah: GT rate-limit ketat (1 request/menit utk IP server) → grafik koin DEX hanya
# punya 1-3 titik (snapshot internal) sehingga terlihat "tidak lengkap".
# Solusi: antrean latar yang SANGAT sabar + cache alamat pool:
#   1 call pertama  : /tokens/{mint}/pools → simpan alamat pool (dipakai selamanya)
#   1 call berikutnya: /pools/{pool}/ohlcv/hour → 48 candle 1 jam (data nyata)
# Nanti refresh tiap 6 jam hanya butuh 1 call per mint.
#
# PENTING: 429 TIDAK boleh mem-blacklist mint (bug lama) — hanya pool kosong/404 yang di-blacklist.
import json, os, time, threading, urllib.request, urllib.error

DIR = os.path.dirname(os.path.abspath(__file__))
RIWAYAT = os.path.join(DIR, "data", "riwayat.json")
SCAN = os.path.join(DIR, "data", "scan.json")
STATE = os.path.join(DIR, "data", "backfill_state.json")
POOLS = os.path.join(DIR, "data", "backfill_pools.json")
GT = "https://api.geckoterminal.com/api/v2"

_lock = threading.Lock()
# statistik untuk /api/backfill
_stats = {"ok": 0, "gagal": 0, "terakhir": None, "pesan": "menunggu"}


def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


class TerlaluSibuk(Exception):
    """GT membalas 429 — jangan hitung sebagai kegagalan permanen."""


def _gt(url, retries=1, backoff=90):
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            return json.loads(urllib.request.urlopen(req, timeout=12).read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                if i < retries:
                    time.sleep(backoff)
                    continue
                raise TerlaluSibuk()
            if e.code == 404:
                return None
            raise
    return None


def _pool_untuk(mint, pools_cache):
    """Alamat pool GT utk mint (cache permanen). None = tidak ada pool."""
    if mint in pools_cache:
        return pools_cache[mint]
    d = _gt(f"{GT}/networks/solana/tokens/{mint}/pools")
    data = (d or {}).get("data") or []
    if not data:
        pools_cache[mint] = ""
        return ""
    best = max(data, key=lambda p: float(
        ((p.get("attributes") or {}).get("reserve_in_usd") or 0)))
    pool = (best.get("attributes") or {}).get("address") or ""
    pools_cache[mint] = pool
    if pool:
        time.sleep(4)  # jeda antar 2 call
    return pool


def backfill_satu(mint, pools_cache=None, refresh=False):
    """Isi/perbarui riwayat 1 mint dari candle GT. Return True bila ada titik baru.
    Raise TerlaluSibuk bila GT 429."""
    pools_cache = pools_cache if pools_cache is not None else _load(POOLS, {})
    with _lock:
        e = _load(RIWAYAT, {}).get(mint) or {}
    unit = e.get("unit", "price")
    pts = list(e.get("points", []))
    punya = {int(p[0]) for p in pts}

    pool = _pool_untuk(mint, pools_cache)
    _save(POOLS, pools_cache)
    if not pool:
        return False

    o = _gt(f"{GT}/networks/solana/pools/{pool}/ohlcv/hour?aggregate=1&limit=48&currency=usd")
    lst = ((o or {}).get("data", {}).get("attributes", {}).get("ohlcv_list")) or []
    if not lst:
        return False

    # Bila seri lama ber-unit "mc" (koin pump.fun), CANGKOK: buang titik yang lebih
    # tua dari candle pertama agar tidak tercampur satuan berbeda.
    candle = [[int(t), float(c)] for t, _o, _h, _l, c, *_ in lst if float(c) > 0]
    if not candle:
        return False
    candle.sort(key=lambda p: p[0])
    if unit != "price":
        pts = [p for p in pts if p[0] >= candle[0][0]]
        unit = "price"

    baru = [p for p in candle if p[0] not in punya]
    pts = sorted(pts + baru, key=lambda p: p[0])[-720:]
    if not baru and not refresh:
        return False

    simbol = e.get("simbol") or "?"
    with _lock:
        rw = _load(RIWAYAT, {})
        lama = rw.get(mint) or {}
        rw[mint] = {"simbol": lama.get("simbol") or simbol,
                    "nama": lama.get("nama", ""), "unit": "price",
                    "points": pts, "gt": True}
        _save(RIWAYAT, rw)
    return True


def _kandidat():
    """Mint koin DEX dari feed yang riwayatnya masih pendek (<40 titik)."""
    scan = _load(SCAN, {})
    rw = _load(RIWAYAT, {})
    out = []
    for lst in (scan.get("menarik_dibeli") or [], scan.get("akumulasi") or [],
                scan.get("solana_alternatif") or [], scan.get("pumpfun_stonk") or []):
        for k in lst:
            m = k.get("mint")
            if not m:
                continue
            e = rw.get(m) or {}
            if e.get("unit") != "price" or len(e.get("points", [])) < 40:
                out.append(m)
    return list(dict.fromkeys(out))


def loop_backfill():
    """1 mint per putaran; 45 detik bila sukses, 150 detik bila GT sibuk (429)."""
    global _stats
    pools_cache = _load(POOLS, {})
    while True:
        jeda = 45
        try:
            st = _load(STATE, {"gagal": [], "ok_ts": {}})
            antre = [m for m in _kandidat() if m not in st.get("gagal", [])]
            if antre:
                m = antre[0]
                try:
                    ok = backfill_satu(m, pools_cache)
                    if ok:
                        st.setdefault("ok_ts", {})[m] = time.time()
                        _stats["ok"] += 1
                        _stats["terakhir"] = m
                        _stats["pesan"] = "sukses"
                        print(f"[backfill] ✓ {m[:10]} riwayat diperbarui")
                    else:
                        st["gagal"] = (st.get("gagal", []) + [m])[-300:]
                        _stats["pesan"] = "tidak ada pool GT"
                        print(f"[backfill] – {m[:10]} tanpa candle")
                except TerlaluSibuk:
                    jeda = 150
                    _stats["pesan"] = "GT 429 — jeda lebih panjang"
                _save(STATE, st)
            else:
                _stats["pesan"] = "semua riwayat lengkap"
                jeda = 300
        except Exception as e:
            print("backfill loop err:", str(e)[:80])
        time.sleep(jeda)


def mulai_backfill_thread():
    threading.Thread(target=loop_backfill, daemon=True).start()


def statistik():
    rw = _load(RIWAYAT, {})
    price = [v for v in rw.values() if v.get("unit") == "price"]
    return {"ok_sesi": _stats["ok"], "pesan": _stats["pesan"],
            "mint_riwayat_harga": len(price),
            "mint_terlengkap": sum(1 for v in price if len(v.get("points", [])) >= 40),
            "dari_gt": sum(1 for v in price if v.get("gt"))}


if __name__ == "__main__":
    print("tes backfill 1 koin...")
    k = _kandidat()
    print("antre:", len(k))
    if k:
        try:
            print(k[0][:12], "->", backfill_satu(k[0]))
        except TerlaluSibuk:
            print(k[0][:12], "-> GT 429 (normal; loop background akan mengulang)")
    print(statistik())
