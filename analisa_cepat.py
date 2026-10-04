# KoinScan — analisa_cepat.py
# Refresh analisa SEMUA koin tiap 60 detik — TANPA request API berat:
#  - tick.py sudah menyimpan MC/umur/reply/live per mint tiap 20 detik (1-2 call pump.fun)
#  - modul ini menghitung ULANG skor untuk semua koin di data/scan.json lalu menulis KEMBALI
#    ke data/scan.json (feed), sehingga /api/feed selalu segar tanpa menunggu scan berat 10 menit.
#  - data sektor (h1/h24/liq untuk koin DEX) diambil dari tick_state + riwayat, bukan API baru.
#
# Dipanggil oleh web_server.auto_refresh tiap 60 detik.
import json, os, time

DIR = os.path.dirname(os.path.abspath(__file__))
SCAN = os.path.join(DIR, "data", "scan.json")
TICK = os.path.join(DIR, "data", "tick_state.json")
RISIKO = os.path.join(DIR, "data", "risiko_cache.json")
TRACK = os.path.join(DIR, "data", "pump_tracker.json")


def _load(p, d):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return d


def _save(p, obj):
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, p)


def skor_ringan(k, st, repo):
    """Skor ulang cepat berbasis data live (tanpa API). Bobot identik filosofi riset."""
    s = 35.0
    mc = (st or {}).get("mc") or k.get("mc") or 0
    umur = None
    if (st or {}).get("created"):
        umur = (time.time() - st["created"]) / 3600
    elif k.get("umur_jam") is not None:
        umur = k["umur_jam"]
    if umur is not None:
        s += 20 if umur < 6 else 12 if umur < 24 else 5 if umur < 72 else 0
    reply = (st or {}).get("reply") or k.get("replies") or 0
    s += min(15, reply / 10 * 15)
    if (st or {}).get("live") or k.get("live"):
        s += 10
    if 30_000 <= mc <= 500_000:
        s += 30
    elif 5_000 <= mc < 30_000:
        s += 20
    elif 500_000 < mc <= 2_000_000:
        s += 15
    if k.get("complete") or (st or {}).get("complete"):
        s += 15
    # momentum harga (koin DEX)
    h1 = k.get("h1") or 0
    h24 = k.get("h24") or 0
    if h1 >= 20:
        s += 8
    elif h1 >= 5:
        s += 4
    elif h1 < -15:
        s -= 10
    if h24 >= 50:
        s += 6
    # tekanan beli
    tb = k.get("tekanan_beli")
    if tb is not None:
        if tb >= 65:
            s += 8
        elif tb <= 40:
            s -= 6
    # putusan risiko (dari cache — TIDAK memanggil RugCheck)
    put = ((k.get("risiko") or {}).get("putusan") or "TIDAK-DIKETAHUI")
    if put == "AMAN-RELATIF" or put == "RELATIF AMAN":
        s += 8
    elif put == "HATI-HATI":
        s -= 6
    elif put in ("BAHAM", "BAHAYA", "SCAM"):
        s -= 30
    # flag BUNDLER / RUG-RISIKO
    for f in (k.get("flag") or []):
        s -= 12
    return round(max(0, min(100, s)), 1)


def analisa_cepat():
    """Hitung ulang skor + MC semua koin di feed dari data live. Return jumlah koin diperbarui."""
    feed = _load(SCAN, {})
    if not feed or "menarik_dibeli" not in feed:
        return 0
    st = _load(TICK, {})
    tr = _load(TRACK, {})
    n = 0
    for kat in ("menarik_dibeli", "pumpfun_baru", "pumpfun_stonk",
                "solana_alternatif", "akumulasi", "terfilter_scam"):
        for k in (feed.get(kat) or []):
            mint = k.get("mint")
            if not mint:
                continue
            t = st.get(mint) or {}
            mc_live = t.get("mc") or 0
            if mc_live > 0:
                k["mc"] = mc_live
                k["mc_live"] = True
            if t.get("created"):
                k["umur_jam"] = round((time.time() - t["created"]) / 3600, 1)
            if t.get("reply"):
                k["replies"] = t["reply"]
            # pertumbuhan sejak dianalisa (tracker)
            ent = tr.get(mint) or {}
            if ent.get("mc_awal") and k.get("mc"):
                k["growth"] = round(k["mc"] / ent["mc_awal"], 2)
            k["skor"] = skor_ringan(k, t, tr)
            k["skor_ts"] = time.time()
            n += 1
    feed["ts_analisa"] = time.time()
    feed["analisa_menit"] = 1
    _save(SCAN, feed)
    return n


if __name__ == "__main__":
    t0 = time.time()
    n = analisa_cepat()
    print(f"analisa_cepat: {n} koin diperbarui dlm {time.time()-t0:.2f}s")
