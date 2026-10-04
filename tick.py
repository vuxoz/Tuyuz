# KoinScan — TICK real-time (tiap 20 detik).
#
# Arsitektur hybrid (kenapa bukan scan penuh tiap 20 detik?):
#   Scan penuh = pump.fun + DexScreener + GeckoTerminal + RugCheck per mint → 2-3 menit
#   dan rate-limit API eksternal akan 429 terus-menerus. Solusi:
#   - SCAN BERAT (10 menit, di scanner.py): semua sumber + analisa risiko RugCheck
#   - TICK 20 DETIK (modul ini): 1 call ringan pump.fun (100 koin terbaru) → update live
#     harga/MC/umur semua koin yang sudah dipindai + deteksi EVENT penting real-time.
#
# EVENT yang dideteksi tiap tick (dipakai fitur "Sinyal Langsung"):
#   🎓 GRADUATED  : koin complete false→true (barusan lulus ke pumpswap)
#   🌋 SPIKE      : MC naik ≥30% dalam <15 menit
#   🎯 DEKAT-LULUS: MC masuk zona $50K–$69K (menuju graduation)
#   🆕 BARU-RILIS : koin muncul pertama kali di feed
#
# File:
#   data/tick_state.json  — status live per mint (mc_tick, ts_tick, complete_tick)
#   data/sinyal.json      — daftar event terkini (max 100)
import json, os, time, threading, urllib.request, urllib.error

DIR = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(DIR, "data", "tick_state.json")
SINYAL = os.path.join(DIR, "data", "sinyal.json")
RIWAYAT = os.path.join(DIR, "data", "riwayat.json")
PUMP = "https://frontend-api-v3.pump.fun"
GRAD_MC = 69_000

_lock = threading.Lock()
_last_ds = {"ts": 0}


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


def _get(url, retries=2, backoff=6):
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            return json.loads(urllib.request.urlopen(req, timeout=12).read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < retries:
                time.sleep(backoff * (i + 1))
                continue
            raise
    return []


def tick_sekali():
    """Satu tick: ambil 100 koin terbaru pump.fun, update state, deteksi event.
    Return jumlah event baru (utk log)."""
    try:
        # DUA SUMBER per tick:
        #  a) koin TERBARU (deteksi BARU-RILIS)
        #  b) koin MC TERTINGGI bonding curve (koin aging yang menanjak — tanpa ini
        #     spike koin berumur >±1 jam terlewat karena sudah keluar halaman "terbaru")
        coins = _get(f"{PUMP}/coins?sort=created_timestamp&order=DESC&limit=100")
        time.sleep(1.2)
        try:
            coins_mc = _get(f"{PUMP}/coins?sort=market_cap&order=DESC&limit=100")
        except Exception:
            coins_mc = []
        # gabung unik per mint
        dilihat = set()
        semua = []
        for c in list(coins) + list(coins_mc):
            m = c.get("mint")
            if m and m not in dilihat:
                dilihat.add(m)
                semua.append(c)
        coins = semua
    except Exception as e:
        print("tick err:", e)
        return 0
    if not coins:
        return 0

    now = time.time()
    events = []
    with _lock:
        state = _load(STATE, {})
        sinyal = _load(SINYAL, [])

        for c in coins:
            mint = c.get("mint")
            if not mint:
                continue
            mc = float(c.get("usd_market_cap") or 0)
            complete = bool(c.get("complete"))
            lama = state.get(mint)

            # --- deteksi event ---
            if not lama:
                # koin muncul pertama kali; hanya laporkan yg cukup menarik (MC > $8K
                # supaya tidak membanjiri sinyal dengan koin lahir 10 detik)
                if mc > 8_000:
                    events.append({"tipe": "BARU-RILIS", "ikon": "🆕", "mint": mint,
                                   "simbol": c.get("symbol", "?"), "nama": c.get("name", ""),
                                   "mc": mc, "waktu": now,
                                   "ket": f"koin baru terdeteksi, MC ${mc:,.0f}"})
            else:
                mc_lama = lama.get("mc") or 0
                ts_lama = lama.get("ts") or now
                dt_menit = max((now - ts_lama) / 60, 0.1)
                if not lama.get("complete") and complete and mc > 0:
                    events.append({"tipe": "GRADUATED", "ikon": "🎓", "mint": mint,
                                   "simbol": c.get("symbol", "?"), "nama": c.get("name", ""),
                                   "mc": mc, "waktu": now,
                                   "ket": "BARUSAN lulus ke pumpswap — momen kritis!"})
                elif mc_lama > 0 and mc / mc_lama >= 2.0 and dt_menit <= 30:
                    events.append({"tipe": "MELONJAK", "ikon": "🚀", "mint": mint,
                                   "simbol": c.get("symbol", "?"), "nama": c.get("name", ""),
                                   "mc": mc, "waktu": now,
                                   "ket": f"melonjak +{(mc/mc_lama-1)*100:.0f}% dalam {dt_menit:.0f} menit — perhatian!"})
                elif mc_lama > 0 and mc / mc_lama >= 1.3 and dt_menit <= 15:
                    events.append({"tipe": "SPIKE", "ikon": "🌋", "mint": mint,
                                   "simbol": c.get("symbol", "?"), "nama": c.get("name", ""),
                                   "mc": mc, "waktu": now,
                                   "ket": f"spike +{(mc/mc_lama-1)*100:.0f}% dalam {dt_menit:.0f} menit"})
                elif mc_lama > 0 and mc / mc_lama >= 1.15 and dt_menit <= 15 and not lama.get("potensi"):
                    # sinyal DINI: kenaikan kecil tapi konsisten — sekali per koin sampai melandai
                    events.append({"tipe": "POTENSI", "ikon": "📈", "mint": mint,
                                   "simbol": c.get("symbol", "?"), "nama": c.get("name", ""),
                                   "mc": mc, "waktu": now,
                                   "ket": f"momentum naik +{(mc/mc_lama-1)*100:.0f}% dalam {dt_menit:.0f} menit"})
                elif not (lama.get("dekat") ) and 50_000 <= mc < GRAD_MC:
                    events.append({"tipe": "DEKAT-LULUS", "ikon": "🎯", "mint": mint,
                                   "simbol": c.get("symbol", "?"), "nama": c.get("name", ""),
                                   "mc": mc, "waktu": now,
                                   "ket": f"{mc/GRAD_MC*100:.0f}% menuju graduation"})

            # --- update state ---
            naik_lagi = mc_lama > 0 and mc / mc_lama >= 1.15
            potensi_baru = bool(lama.get("potensi")) and naik_lagi
            if mc_lama > 0 and mc / mc_lama < 1.02:
                potensi_baru = False  # momentum habis → boleh sinyal lagi saat naik berikutnya
            state[mint] = {"simbol": c.get("symbol", "?"), "nama": c.get("name", ""),
                           "mc": mc, "ts": now, "complete": complete,
                           "dekat": 50_000 <= mc < GRAD_MC,
                           "potensi": potensi_baru,
                           "reply": int(c.get("reply_count") or 0),
                           "live": bool(c.get("is_currently_live")),
                           "img": (c.get("image_uri") or "").strip(),
                           "created": (c.get("created_timestamp") or 0) / 1000}
        # simpan hanya 2000 mint terakhir
        if len(state) > 2000:
            urut = sorted(state.items(), key=lambda kv: -(kv[1].get("ts") or 0))
            state = dict(urut[:2000])
        if events:
            sinyal = (events + sinyal)[:100]
        _save(STATE, state)
        _save(SINYAL, sinyal)

    # --- riwayat utk grafik (di luar lock state) ---
    try:
        riwayat = _load(RIWAYAT, {})
        for c in coins:
            mint = c.get("mint")
            if not mint:
                continue
            mc = float(c.get("usd_market_cap") or 0)
            e = riwayat.setdefault(mint, {"simbol": c.get("symbol", "?"),
                                          "nama": c.get("name", ""),
                                          "unit": "mc", "points": []})
            if e.get("unit") != "mc":
                e["unit"], e["points"] = "mc", []  # satuan berubah → reset seri
            pts = e["points"]
            if pts and now - pts[-1][0] < 15:
                pts[-1] = [now, mc]  # dedupe tick ganda
            else:
                pts.append([now, mc])
            # simpan maks ~4 jam (720 titik @20s)
            if len(pts) > 720:
                e["points"] = pts[-720:]
        # buang koin tak update >12 jam, maks 600 mint
        if len(riwayat) > 600:
            cut = now - 12 * 3600
            riwayat = {m: v for m, v in riwayat.items()
                       if v["points"] and v["points"][-1][0] > cut}
        _save(RIWAYAT, riwayat)
    except Exception as e:
        print("riwayat err:", e)

    # --- snapshot harga koin DEX teratas (sumber grafik jangka panjang) ---
    try:
        if now - _last_ds.get("ts", 0) > 180:  # tiap 3 menit (DexScreener longgar)
            _last_ds["ts"] = now
            scan = _load(os.path.join(DIR, "data", "scan.json"), {})
            top = (scan.get("menarik_dibeli") or [])[:20] + (scan.get("akumulasi") or [])[:10]
            mints = [k["mint"] for k in top if k.get("mint")]
            if mints:
                req = urllib.request.Request(
                    "https://api.dexscreener.com/latest/dex/tokens/" + ",".join(mints),
                    headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
                dd = json.loads(urllib.request.urlopen(req, timeout=10).read())
                by = {}
                for p in (dd.get("pairs") or []):
                    m = p.get("baseToken", {}).get("address")
                    if not m:
                        continue
                    if m not in by or float(p.get("liquidity", {}).get("usd") or 0) > by[m][0]:
                        by[m] = (float(p.get("liquidity", {}).get("usd") or 0), p)
                rw = _load(RIWAYAT, {})
                for m, (liq, p) in by.items():
                    harga = float(p.get("priceUsd") or 0)
                    if harga <= 0:
                        continue
                    e = rw.setdefault(m, {"simbol": p["baseToken"].get("symbol", "?"),
                                          "nama": p["baseToken"].get("name", ""),
                                          "unit": "price", "points": []})
                    if e.get("unit") != "price":
                        e["unit"], e["points"] = "price", []
                    pts = e["points"]
                    if pts and now - pts[-1][0] < 60:
                        pts[-1] = [now, harga]
                    else:
                        pts.append([now, harga])
                    if len(pts) > 720:
                        e["points"] = pts[-720:]
                # gabung dgn entri tick (jangan timpa koin pump.fun yg unit-nya mc)
                rw_tick = _load(RIWAYAT, {})
                for m, v in rw.items():
                    if m not in rw_tick or rw_tick[m].get("unit") != "mc":
                        rw_tick[m] = v
                _save(RIWAYAT, rw_tick)
    except Exception as e:
        print("snapshot dex err:", e)
    return len(events)


def loop_tick(interval=20):
    while True:
        try:
            n = tick_sekali()
            if n:
                print(f"[tick] {n} event baru")
        except Exception as e:
            print("tick loop err:", e)
        time.sleep(interval)


def mulai_tick_thread(interval=20):
    threading.Thread(target=loop_tick, args=(interval,), daemon=True).start()


def sinyal_terkini(limit=50):
    with _lock:
        return _load(SINYAL, [])[:limit]


def statistik_tick():
    st = _load(STATE, {})
    now = time.time()
    live = [v for v in st.values() if now - (v.get("ts") or 0) < 120]
    return {"total_dilacak_tick": len(st), "aktif_2menit": len(live),
            "interval": 20}


if __name__ == "__main__":
    print("tes 3 tick...")
    for i in range(3):
        n = tick_sekali()
        print(f"tick {i+1}: {n} event")
        time.sleep(5)
    print(json.dumps(sinyal_terkini(5), indent=1, ensure_ascii=False))
    print(statistik_tick())
