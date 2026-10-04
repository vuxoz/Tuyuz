# KoinScan — web server (stdlib http.server), sajikan API JSON + halaman analisa
import json, os, threading, time, urllib.request, urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import scanner  # pindai() + auto-refresh thread
import pump_riset  # tracker riset pump.fun (img koin)
import tick     # tick 20 detik + deteksi sinyal
import backfill # backfill riwayat grafik koin DEX (GT OHLCV, sabar)
import risiko   # analisa risiko per mint (utk fitur Cek Koin)

HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
HALAMAN = {"/": "index.html", "/pumpfun": "pumpfun.html",
           "/graduated": "graduated.html", "/alternatif": "alternatif.html",
           "/akumulasi": "akumulasi.html", "/scam": "scam.html",
           "/sinyal": "sinyal.html", "/cek": "cek.html", "/watchlist": "watchlist.html",
           "/grafik": "grafik.html", "/top": "top.html", "/tentang": "tentang.html",
           "/multichain": "multichain.html"}


def auto_refresh():
    """Analisa cepat 60 detik (skor ulang dari data live tick) + scan berat 10 menit."""
    import analisa_cepat
    terakhir_berat = 0
    while True:
        try:
            # ⚡ ANALISA RINGAN tiap 60 detik: hitung ulang skor/MC semua koin dari data tick
            #    (nol request API eksternal — aman dari rate-limit)
            n = analisa_cepat.analisa_cepat()
            if n:
                print(f"[analisa-cepat] {n} koin skor-ulang")
        except Exception as e:
            print("analisa cepat error:", e)
        # 📈 snapshot harga multi-chain tiap 60 detik → grafik koin EVM tumbuh seiring waktu
        try:
            import multichain as _mcmod
            rw = tick._load(tick.RIWAYAT, {})
            berubah = False
            for k in (_mcmod.papan_multichain().get("koin") or []):
                h = _mcmod._num(k.get("harga")) or _mcmod._num(k.get("price"))
                m = k.get("mint") or ""
                if h > 0 and m:
                    e = rw.setdefault(m, {"simbol": k.get("simbol", "?"), "nama": k.get("nama", ""),
                                          "unit": "price", "points": []})
                    if e.get("unit") != "price":
                        e["unit"], e["points"] = "price", []
                    now = time.time()
                    pts = e["points"]
                    if not pts or now - pts[-1][0] >= 50:
                        pts.append([now, h])
                        e["points"] = pts[-720:]
                        berubah = True
            if berubah:
                tick._save(tick.RIWAYAT, rw)
                print("[mc-snapshot] harga multichain tersimpan")
        except Exception as e:
            print("mc snapshot error:", e)
        # 🔬 scan berat (semua sumber + RugCheck) tetap 10 menit sekali
        if time.time() - terakhir_berat >= 600:
            try:
                scanner.pindai(force=True)
                terakhir_berat = time.time()
                print("[scan-berat] selesai")
            except Exception as e:
                print("refresh error:", e)
        time.sleep(60)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, nama="index.html"):
        with open(os.path.join(HTML, nama), "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")  # deploy statis selalu segar
        self.end_headers()
        self.wfile.write(body)

    def _statis(self, nama):
        path = os.path.join(HTML, nama)
        if not os.path.isfile(path):
            self._json({"error": "not found"}, 404)
            return
        tipe = {"css": "text/css", "js": "application/javascript"}.get(
            nama.rsplit(".", 1)[-1], "application/octet-stream")
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", f"{tipe}; charset=utf-8")
        self.send_header("Cache-Control", "max-age=300")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        path, q = u.path, parse_qs(u.query)
        if path in HALAMAN:
            self._html(HALAMAN[path])
        elif path.startswith("/static/"):
            self._statis(path[len("/static/"):])
        elif path == "/api/feed":
            feed = scanner.pindai()  # cache segar → instan; kosong → mulai scan bg
            if "menarik_dibeli" in feed:
                feed["tick"] = tick.statistik_tick()
                # ⚡ REAL-TIME OVERLAY: timpa MC/harga tiap koin dgn nilai tick terakhir (≤20 dtk lalu),
                #    bukan nilai saat scan berat 10 menit yang lalu. Hitung ulang growth.
                st_tick = tick._load(tick.STATE, {})
                for kat in ("menarik_dibeli", "pumpfun_baru", "pumpfun_stonk",
                            "solana_alternatif", "akumulasi", "terfilter_scam"):
                    for k in (feed.get(kat) or []):
                        t = st_tick.get(k.get("mint"))
                        if not t:
                            continue
                        mc_live = t.get("mc") or 0
                        if mc_live > 0:
                            k["mc"] = mc_live
                            k["mc_live"] = True
                            if t.get("created"):
                                k["umur_jam"] = round(
                                    (time.time() - t["created"]) / 3600, 1)

                # 🚫 buang koin duplikat lintas papan (mint sama hanya boleh tampil SEKALI;
                #    urutan prioritas: menarik > pumpfun_baru > stonk > alternatif > akumulasi > scam)
                urutan = ("menarik_dibeli", "pumpfun_baru", "pumpfun_stonk",
                          "solana_alternatif", "akumulasi", "terfilter_scam")
                terlihat = set()
                for kat in urutan:
                    lst = feed.get(kat) or []
                    unik = []
                    for k in lst:
                        # kunci dedupe: mint unik, TAPI juga simbol+logo & simbol+nama
                        # (koin re-upload dgn banner/nama sama = duplikat, mint beda pun dibuang)
                        kunci = set()
                        if k.get("mint"):
                            kunci.add("m:" + k["mint"])
                        sim = (k.get("simbol") or "").strip().upper()
                        if sim:
                            kunci.add("s:" + sim)
                            if k.get("logo") or k.get("img"):
                                kunci.add("sl:" + sim + "|" + (k.get("logo") or k.get("img")))
                            if k.get("nama"):
                                kunci.add("sn:" + sim + "|" + (k.get("nama") or "").strip().lower())
                        if kunci & terlihat:
                            continue
                        terlihat |= kunci
                        unik.append(k)
                    feed[kat] = unik

                # 🖼️ pastikan logo terisi dari cache map (scan berikutnya akan melengkapi)
                try:
                    lmap = scanner._load_json(scanner.LOGO_MAP)
                    kosong = []
                    for kat in ("menarik_dibeli", "pumpfun_baru", "pumpfun_stonk",
                                "solana_alternatif", "akumulasi", "terfilter_scam"):
                        for k in feed.get(kat) or []:
                            if not k.get("logo"):
                                u = lmap.get(k.get("mint") or "", "")
                                if u:
                                    k["logo"] = u
                                else:
                                    kosong.append(k.get("mint"))
                    if kosong:
                        scanner.simpan_logo_map(list(dict.fromkeys(kosong))[:120])
                        lmap = scanner._load_json(scanner.LOGO_MAP)
                        for kat in ("menarik_dibeli", "pumpfun_baru", "pumpfun_stonk",
                                    "solana_alternatif", "akumulasi", "terfilter_scam"):
                            for k in feed.get(kat) or []:
                                if not k.get("logo"):
                                    k["logo"] = lmap.get(k.get("mint") or "", "")
                except Exception as e:
                    print("logo feed err:", e)
                self._json(feed)
            else:
                self._json({"status": "scanning",
                            "pesan": "Scan pertama sedang berjalan (~3 menit), refresh sebentar lagi."})
        elif path == "/api/logo":
            mint = (q.get("mint") or [""])[0]
            self._json({"mint": mint, "logo": scanner.logo_untuk(mint) or ""})
        elif path == "/api/backfill":
            self._json(backfill.statistik())
        elif path == "/api/analisa":
            import analisa_ai
            mint = (q.get("mint") or [""])[0]
            a = analisa_ai.analisa_mint(mint)
            if a:
                self._json(a)
            else:
                self._json({"error": "koin tidak ditemukan di data analisa"}, 404)
        elif path == "/api/multichain":
            import multichain
            self._json(multichain.papan_multichain())
        elif path == "/api/movers":
            # 🔥 TOP MOVERS SEJAK DIANALISA: kenaikan MC dari mc_awal (saat koin pertama
            # kali masuk analisa KoinScan) ke MC live tick sekarang (≤20 dtk lalu).
            tr = pump_riset._load(pump_riset.TRACK_FILE, {})
            st_tick = tick._load(tick.STATE, {})
            lmap = scanner._load_json(scanner.LOGO_MAP) if hasattr(scanner, "LOGO_MAP") else {}
            baris = []
            for mint, ent in tr.items():
                mc_awal = ent.get("mc_awal") or 0
                mc_now = (st_tick.get(mint) or {}).get("mc") or ent.get("mc") or 0
                if mc_awal <= 0 or mc_now <= 0:
                    continue
                growth = mc_now / mc_awal
                # hanya kenaikan riil yang layak papan; MC awal sangat kecil dibatasi biar % tak menipu
                if growth < 1.1 or mc_now < 5_000:
                    continue
                baris.append({
                    "mint": mint,
                    "simbol": ent.get("simbol", "?"),
                    "nama": ent.get("nama", ""),
                    "img": ent.get("img", "") or lmap.get(mint, ""),
                    "mc_awal": round(mc_awal),
                    "mc": round(mc_now),
                    "kenaikan_pct": round((growth - 1) * 100, 1),
                    "growth": round(growth, 2),
                    "dianalisa": ent.get("pertama_dilihat"),
                    "umur_analisa_jam": round((time.time() - ent.get("pertama_dilihat", time.time())) / 3600, 1),
                })
            baris.sort(key=lambda x: -x["growth"])
            self._json({"ts": time.time(), "total": len(baris), "movers": baris[:50]})
        elif path == "/api/sinyal":
            sinyal = tick.sinyal_terkini(int((q.get("limit") or ["50"])[0]))
            # 🖼️ logo sinyal dari tracker riset (img pump.fun) + logo_map (DexScreener)
            try:
                tr = pump_riset._load(pump_riset.TRACK_FILE, {})
            except Exception:
                tr = {}
            lmap = {}
            try:
                import os as _os
                with open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data", "logo_map.json")) as _f:
                    lmap = json.load(_f)
            except Exception:
                pass
            # 📊 DETAIL LENGKAP tiap sinyal: MC live, umur, growth, risiko, proyek, skor AI
            import analisa_ai
            st_tick = tick._load(tick.STATE, {})
            pmap = {}
            try:
                with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "proyek_map.json")) as _f:
                    pmap = json.load(_f)
            except Exception:
                pass
            for sg in sinyal or []:
                m = sg.get("mint")
                ent = tr.get(m) or {}
                t = st_tick.get(m) or {}
                sg["img"] = ent.get("img") or t.get("img") or lmap.get(m, "")
                mc_live = t.get("mc") or sg.get("mc") or 0
                sg["mc_live"] = round(mc_live)
                sg["umur_jam"] = round((time.time() - t["created"]) / 3600, 1) \
                    if t.get("created") else None
                if ent.get("mc_awal") and mc_live:
                    g = mc_live / ent["mc_awal"]
                    sg["growth"] = round(g, 2)
                    sg["kenaikan_pct"] = round((g - 1) * 100, 1)
                sg["reply"] = t.get("reply") or ent.get("reply") or 0
                sg["complete"] = t.get("complete")
                # risiko dari cache scan.json
                try:
                    feed = scanner.pindai()
                    rr = None
                    for kat in ("menarik_dibeli", "pumpfun_baru", "pumpfun_stonk",
                                "solana_alternatif", "akumulasi", "terfilter_scam"):
                        for k2 in (feed.get(kat) or []):
                            if k2.get("mint") == m:
                                rr = k2.get("risiko"); break
                        if rr: break
                    sg["risiko"] = rr
                except Exception:
                    sg["risiko"] = None
                # proyek: deskripsi + sosial
                pr = pmap.get(m) or {}
                sg["proyek"] = {"deskripsi": pr.get("description") or "",
                                "website": pr.get("website") or "",
                                "twitter": pr.get("twitter") or "",
                                "telegram": pr.get("telegram") or ""}
                # skor AI
                try:
                    a = analisa_ai.analisa_mint(m)
                    if a:
                        sg["skor_ai"] = a["skor_ai"]
                        sg["putusan_ai"] = a["putusan"]
                        sg["ai_kekuatan"] = a["kekuatan"]
                        sg["ai_hati"] = a["hati_hati"]
                except Exception:
                    pass
            # 🪙 LIST KOIN SUDAH DIANALISA — dari analisa_cepat (refresh 1 menit), selalu ada
            koin_analisa = []
            try:
                with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "scan.json")) as _f:
                    _scan = json.load(_f)
                lmap2 = lmap
                for kat in ("menarik_dibeli", "pumpfun_baru", "pumpfun_stonk",
                            "solana_alternatif", "akumulasi"):
                    for k2 in (_scan.get(kat) or []):
                        m2 = k2.get("mint")
                        if not m2 or m2 in {x.get("mint") for x in koin_analisa}:
                            continue
                        t2 = st_tick.get(m2) or {}
                        ent2 = tr.get(m2) or {}
                        a2 = None
                        try:
                            a2 = analisa_ai.analisa_mint(m2)
                        except Exception:
                            a2 = None
                        pr2 = pmap.get(m2) or {}
                        koin_analisa.append({
                            "mint": m2, "simbol": k2.get("simbol"), "nama": k2.get("nama"),
                            "sumber": k2.get("sumber"), "tipe": "ANALISA",
                            "ikon": "📊",
                            "ket": "skor AI dihitung ulang tiap 1 menit",
                            "img": k2.get("img") or ent2.get("img") or t2.get("img") or lmap2.get(m2, ""),
                            "mc": k2.get("mc"), "mc_live": round(t2.get("mc") or k2.get("mc") or 0),
                            "skor": k2.get("skor"), "liq": k2.get("liq"),
                            "h1": k2.get("h1"), "h24": k2.get("h24"),
                            "vol24": k2.get("vol24"), "tekanan_beli": k2.get("tekanan_beli"),
                            "umur_jam": round((time.time() - t2["created"]) / 3600, 1) if t2.get("created") else k2.get("umur_jam"),
                            "growth": ent2.get("growth_riil"),
                            "reply": t2.get("reply") or 0,
                            "risiko": k2.get("risiko"),
                            "proyek": {"deskripsi": pr2.get("description") or "",
                                       "website": pr2.get("website") or "",
                                       "twitter": pr2.get("twitter") or "",
                                       "telegram": pr2.get("telegram") or ""},
                            "skor_ai": (a2 or {}).get("skor_ai"),
                            "putusan_ai": (a2 or {}).get("putusan"),
                            "ai_kekuatan": (a2 or {}).get("kekuatan"),
                            "ai_hati": (a2 or {}).get("hati_hati"),
                            "waktu": time.time(),
                        })
            except Exception as _e:
                pass
            koin_analisa.sort(key=lambda x: -(x.get("skor_ai") or x.get("skor") or 0))
            self._json({"ts": time.time(), "waktu": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "sinyal": sinyal, "koin_analisa": koin_analisa[:60],
                        "tick": tick.statistik_tick(),
                        "interval_analisa": 60})
        elif path == "/api/proyek":
            # MODE BATCH: ?mints=a,b,c → cache-only (instan, tanpa jaringan) + logo
            batch = (q.get("mints") or [""])[0].strip()
            if batch:
                mints = [x.strip() for x in batch.split(",") if x.strip()][:80]
                out = {}
                try:
                    import proyek as _pj
                    cache = _pj._muat()
                except Exception:
                    cache = {}
                try:
                    import os as _os
                    lmap = json.load(open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data", "logo_map.json")))
                except Exception:
                    lmap = {}
                for m in mints:
                    p = cache.get(m) or {}
                    out[m] = {"deskripsi": p.get("deskripsi", ""), "website": p.get("website", ""),
                              "twitter": p.get("twitter", ""), "telegram": p.get("telegram", ""),
                              "banner": p.get("banner", ""), "logo": lmap.get(m, "")}
                self._json({"proyek": out})
                return
            mint = (q.get("mint") or [""])[0].strip()
            if not mint:
                self._json({"error": "parameter mint kosong"}, 400)
                return
            meta, ds_info = None, None
            # metadata_uri: 1) tracker riset  2) feed pumpfun_baru
            try:
                tr = pump_riset._load(pump_riset.TRACK_FILE, {})
                meta = (tr.get(mint) or {}).get("metadata_uri") or None
            except Exception:
                pass
            if not meta:
                try:
                    feed = scanner.pindai()
                    for kat in ("pumpfun_baru", "pumpfun_stonk", "menarik_dibeli"):
                        for k in feed.get(kat) or []:
                            if k.get("mint") == mint:
                                meta = meta or k.get("metadata_uri") or None
                                break
                except Exception:
                    pass
            # ds_info: DexScreener info utk koin DEX
            try:
                pairs = scanner.ds_graduated([mint])
                if pairs:
                    ds_info = (pairs[0] or {}).get("info") or None
            except Exception:
                pass
            try:
                import proyek
                self._json(proyek.info_proyek(mint, metadata_uri=meta, ds_info=ds_info))
            except Exception as e:
                self._json({"mint": mint, "deskripsi": "", "galat": str(e)[:80]})
        elif path == "/api/cek":
            mint = (q.get("mint") or [""])[0].strip()
            if not mint:
                self._json({"error": "parameter mint kosong"}, 400)
                return
            self._json(cek_koin(mint))
        elif path == "/api/grafik":
            mint = (q.get("mint") or [""])[0].strip()
            if not mint:
                self._json({"error": "parameter mint kosong"}, 400)
                return
            self._json(grafik_data(mint))
        else:
            self._json({"error": "not found"}, 404)


GRAFIK_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "grafik_cache.json")
GRAFIK_TTL = 600  # 10 menit per mint


def _gt_get(url, timeout=8, retries=2, backoff=6):
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < retries:
                time.sleep(backoff * (i + 1))
                continue
            raise


def grafik_data(mint):
    """Data grafik harga/MC koin.
    Sumber 1 (utama, tanpa rate-limit): riwayat snapshot internal — tick 20 detik (pump.fun MC)
    + snapshot harga DexScreener on-demand (koin DEX, harga USDC).
    Sumber 2 (best effort): OHLCV GeckoTerminal bila kuota tersedia.
    Di-cache 60 detik per mint (snapshot dianimasikan terus oleh tick)."""
    # cache pendek
    try:
        cache = json.load(open(GRAFIK_CACHE)) if os.path.isfile(GRAFIK_CACHE) else {}
        ent = cache.get(mint)
        if ent and time.time() - ent["ts"] < 60:
            return ent["data"]
    except Exception:
        cache = {}
    out = {"mint": mint, "sumber": None, "simbol": "?", "nama": "", "unit": "mc",
           "candles": [], "points": [], "ts": time.time()}

    # 1. riwayat internal (tick pump.fun + snapshot dex)
    try:
        rw = tick._load(tick.RIWAYAT, {}).get(mint)
        if rw:
            out["simbol"] = rw.get("simbol", "?")
            out["nama"] = rw.get("nama", "")
            out["points"] = [p for p in rw.get("points", []) if p[1]]
            out["unit"] = rw.get("unit", "mc")
            if out["points"]:
                out["sumber"] = ("Riwayat snapshot KoinScan (MC, 20 detik/titik)"
                                 if out["unit"] == "mc" else
                                 "Harga DexScreener (snapshot tiap akses)")
    except Exception:
        pass

    # 2. koin DEX: harga via DexScreener (longgar) → simpan snapshot ke riwayat juga
    harga_now = None
    try:
        d = _gt_get("https://api.dexscreener.com/latest/dex/tokens/" + mint, timeout=8)
        pairs = d.get("pairs") or []
        if pairs:
            p = max(pairs, key=lambda x: float(x.get("liquidity", {}).get("usd") or 0))
            out["simbol"] = p["baseToken"].get("symbol", out["simbol"])
            out["nama"] = p["baseToken"].get("name", out["nama"])
            out["pasar"] = {"harga": float(p.get("priceUsd") or 0),
                            "mc": float(p.get("marketCap") or 0),
                            "liq": float((p.get("liquidity") or {}).get("usd") or 0),
                            "h1": p.get("priceChange", {}).get("h1"),
                            "h24": p.get("priceChange", {}).get("h24")}
            harga_now = out["pasar"]["harga"]
            if harga_now and harga_now > 0:
                # catat snapshot harga utk grafik berikutnya
                rw = tick._load(tick.RIWAYAT, {})
                e = rw.setdefault(mint, {"simbol": out["simbol"], "nama": out["nama"],
                                         "unit": "price", "points": []})
                if e.get("unit") != "price":
                    e["unit"], e["points"] = "price", []  # satuan berubah → reset seri
                now = time.time()
                pts = e["points"]
                if harga_now <= 0:
                    pass  # koin bonding curve belum terdaftar DEX — jangan simpan 0
                elif pts and now - pts[-1][0] < 15:
                    pts[-1] = [now, harga_now]
                else:
                    pts.append([now, harga_now])
                e["points"] = pts[-720:]
                tick._save(tick.RIWAYAT, rw)
                out["points"] = [p for p in e["points"] if p[1]]
                out["unit"] = "price"
                out["sumber"] = "Harga DexScreener (snapshot tiap akses)"
    except Exception as e:
        out["galat_ds"] = str(e)[:80]

    # 3. best effort: OHLCV GeckoTerminal (sering 429 — abaikan bila gagal)
    try:
        d = _gt_get(f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{mint}/pools", retries=0)
        pools = d.get("data") or []
        if pools:
            pool = (pools[0].get("attributes") or {}).get("address")
            if pool and not out["points"]:
                for tf, agg, n in (("minute", 15, 96), ("hour", 1, 72), ("day", 1, 90)):
                    try:
                        o = _gt_get(f"https://api.geckoterminal.com/api/v2/networks/"
                                    f"solana/pools/{pool}/ohlcv/{tf}?aggregate={agg}&limit={n}&currency=usd", retries=0)
                        lst = (o.get("data", {}).get("attributes", {}).get("ohlcv_list") or [])
                        if lst:
                            out["sumber"] = f"GeckoTerminal OHLCV ({tf} agg {agg})"
                            out["candles"] = [[t*1000, o_, h, l, c] for t, o_, h, l, c, *_ in reversed(lst)]
                            # simpan close candle ke riwayat → grafik tetap lengkap offline
                            try:
                                rw = tick._load(tick.RIWAYAT, {})
                                e = rw.get(mint) or {"simbol": out["simbol"], "nama": out["nama"], "unit": "price", "points": []}
                                if e.get("unit") == "price":
                                    have = {int(p[0]) for p in e["points"]}
                                    for t_, o2, h2, l2, c2, *_ in lst:
                                        if int(t_) not in have and c2 > 0:
                                            e["points"].append([int(t_), float(c2)])
                                    e["points"].sort(key=lambda p: p[0])
                                    e["points"] = e["points"][-720:]
                                    rw[mint] = e
                                    tick._save(tick.RIWAYAT, rw)
                                    out["points"] = e["points"]
                            except Exception:
                                pass
                            break
                    except Exception:
                        continue
    except Exception:
        pass

    # 2b. KOIN MULTI-CHAIN (bukan Solana): OHLCV GeckoTerminal jaringan yang sesuai.
    #     Chain dideteksi dari papan multichain / pola alamat; grafik yang tadinya blank jadi hidup.
    if len(out.get("points") or []) < 5 and not out["candles"]:
        chain = None
        pool_addr = None
        try:
            import multichain as _mc
            for k in (_mc.papan_multichain().get("koin") or []):
                if k.get("mint") == mint:
                    chain = k.get("chain")
                    pool_addr = k.get("pool") or k.get("pair")
                    break
        except Exception:
            chain = None
        # pool address DexScreener (pairAddress) — tanpa panggilan GT ekstra
        if not chain and mint.startswith("0x"):
            try:
                d0 = _gt_get("https://api.dexscreener.com/latest/dex/tokens/" + mint, timeout=8)
                pairs0 = d0.get("pairs") or []
                if pairs0:
                    p0 = max(pairs0, key=lambda x: float(x.get("liquidity", {}).get("usd") or 0))
                    chain = p0.get("chainId")
                    pool_addr = p0.get("pairAddress")
            except Exception:
                pass
        if not chain:
            # fallback: EVM address (0x...) → coba jaringan umum satu-satu (hemat kuota: max 2)
            if mint.startswith("0x"):
                for net in ("bsc", "ethereum", "base"):
                    try:
                        d2 = _gt_get(f"https://api.geckoterminal.com/api/v2/networks/{net}/tokens/{mint}/pools", retries=0)
                        if d2.get("data"):
                            chain = net
                            pool_addr = (d2["data"][0].get("attributes") or {}).get("address")
                            break
                    except Exception:
                        continue
                    time.sleep(2)
        if chain:
            try:
                if not pool_addr:
                    d3 = _gt_get(f"https://api.geckoterminal.com/api/v2/networks/{chain}/tokens/{mint}/pools", retries=0)
                    if d3.get("data"):
                        pool_addr = (d3["data"][0].get("attributes") or {}).get("address")
                if pool_addr:
                    for tf, agg, n in (("minute", 15, 96), ("hour", 1, 72), ("day", 1, 90)):
                        try:
                            o = _gt_get(f"https://api.geckoterminal.com/api/v2/networks/{chain}/pools/{pool_addr}/ohlcv/{tf}?aggregate={agg}&limit={n}&currency=usd", retries=0)
                            lst = (o.get("data", {}).get("attributes", {}).get("ohlcv_list") or [])
                            if lst:
                                out["sumber"] = f"GeckoTerminal OHLCV {chain} ({tf} agg {agg})"
                                out["candles"] = [[t*1000, o_, h, l, c] for t, o_, h, l, c, *_ in reversed(lst)]
                                # simpan close ke riwayat agar grafik tetap ada offline
                                try:
                                    rw = tick._load(tick.RIWAYAT, {})
                                    e = rw.get(mint) or {"simbol": out["simbol"], "nama": out["nama"], "unit": "price", "points": []}
                                    if e.get("unit") == "price":
                                        have = {int(p[0]) for p in e["points"]}
                                        for t_, _o2, _h2, _l2, c2, *_ in lst:
                                            if int(t_) not in have and c2 > 0:
                                                e["points"].append([int(t_), float(c2)])
                                        e["points"].sort(key=lambda p: p[0])
                                        e["points"] = e["points"][-720:]
                                        rw[mint] = e
                                        tick._save(tick.RIWAYAT, rw)
                                        out["points"] = e["points"]
                                except Exception:
                                    pass
                                break
                        except Exception:
                            continue
            except Exception:
                pass

    if out["simbol"] == "?":
        out["simbol"] = mint[:6]
    try:
        cache[mint] = {"ts": time.time(), "data": out}
        json.dump(cache, open(GRAFIK_CACHE, "w"))
    except Exception:
        pass
    return out


def cek_koin(mint):
    """Fitur Cek Koin: tempel alamat kontrak (CA) Solana → analisa instan.
    Gabungan: risiko RugCheck + data pasar DexScreener + skor riset tracker."""
    out = {"mint": mint, "ts": time.time(), "waktu": time.strftime("%Y-%m-%d %H:%M:%S")}
    # 1. risiko (honeypot/bundler/rug/scam)
    try:
        out["risiko"] = risiko.analisa_mint(mint)
    except Exception as e:
        out["risiko"] = {"putusan": "TIDAK-DIKETAHUI", "flag": [], "galat": str(e)[:80]}
    # 2. data pasar (DexScreener)
    try:
        import scanner as sc
        pairs = sc._get(f"https://api.dexscreener.com/latest/dex/tokens/{mint}").get("pairs") or []
        if pairs:
            p = max(pairs, key=lambda x: float(x.get("liquidity", {}).get("usd") or 0))
            out["pasar"] = sc.ds_fmt(p)
        else:
            out["pasar"] = None
    except Exception as e:
        out["pasar"] = {"galat": str(e)[:80]}
    # 3. riset tracker (kalau koin pernah terlacak)
    try:
        import pump_riset as pr
        ent = pr._load(pr.TRACK_FILE, {}).get(mint)
        if ent:
            skor, alasan = pr.nilai(ent, pr._load(pr.CREATOR_FILE, {}))
            out["riset"] = {"skor": skor, "alasan": alasan, "poll": ent.get("poll", 0),
                            "growth": round((ent.get("mc") or 0) / (ent.get("mc_awal") or 1), 2),
                            "konsisten": ent.get("konsisten", 0),
                            "umur_jam": round((time.time() - (ent.get("pertama_dilihat") or time.time())) / 3600, 2)}
        else:
            out["riset"] = None
    except Exception as e:
        out["riset"] = {"galat": str(e)[:80]}
    # 4. verdict ringkas
    r = out.get("risiko") or {}
    put = r.get("putusan", "TIDAK-DIKETAHUI")
    p = out.get("pasar") or {}
    liq = p.get("liq") or 0
    if put in ("SCAM", "BAHAYA"):
        out["verdict"] = {"level": "HINDARI", "warna": "red",
                          "pesan": f"Risiko tinggi: {put}. " + (", ".join(f.get("tipe", "") for f in r.get("flag", [])[:3]))}
    elif put == "TIDAK-DIKETAHUI":
        out["verdict"] = {"level": "TIDAK DIKETAHUI", "warna": "gray",
                          "pesan": "Belum ada data analisa. Koin sangat baru / belum terindeks."}
    elif liq and liq < 10_000:
        out["verdict"] = {"level": "HATI-HATI", "warna": "amber",
                          "pesan": f"Likuiditas rendah (${liq:,.0f}) — mudah dimanipulasi."}
    else:
        out["verdict"] = {"level": "RELATIF AMAN", "warna": "green",
                          "pesan": "Tidak ada pola scam terdeteksi. Tetap DYOR — meme coin selalu berisiko."}
    return out


if __name__ == "__main__":
    threading.Thread(target=auto_refresh, daemon=True).start()
    tick.mulai_tick_thread(20)  # ⏱ analisa cepat tiap 20 detik
    backfill.mulai_backfill_thread()  # 📈 lengkapi riwayat grafik koin DEX
    from http.server import ThreadingHTTPServer
    port = int(os.environ.get("PORT") or os.environ.get("KOINSCAN_PORT", "8090"))
    print(f"KoinScan web di http://0.0.0.0:{port} (tick 20 detik aktif)")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
