# KoinScan — Analisa AI ringkas per koin (metode riset multi-faktor).
# Bukan LLM berbayar: engine skor berbobot ala riset kuantitatif — data risiko (RugCheck/GMGN),
# momentum (tick), struktur pasar (MC/likuiditas), umur, sosial, tekanan beli → narasi Indonesia.
import json, os, time

DIR = os.path.dirname(os.path.abspath(__file__))

def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default

def _scan():
    return _load(os.path.join(DIR, "data", "scan.json"), {})

def _tick_state():
    return _load(os.path.join(DIR, "data", "tick_state.json"), {})

def _tracker():
    return _load(os.path.join(DIR, "data", "pump_tracker.json"), {})


def analisa_mint(mint):
    """Return dict: skor_ai 0-100, putusan, kekuatan[], risiko[], narasi (ID)."""
    scan = _scan()
    koin = None
    kategori = None
    for kat in ("menarik_dibeli", "pumpfun_baru", "pumpfun_stonk",
                "solana_alternatif", "akumulasi", "terfilter_scam"):
        for k in (scan.get(kat) or []):
            if k.get("mint") == mint:
                koin = k; kategori = kat; break
        if koin:
            break
    if not koin:
        # cari di tracker riset
        ent = _tracker().get(mint)
        if not ent:
            return None
        koin = {"simbol": ent.get("simbol"), "nama": ent.get("nama"), "mint": mint,
                "mc": ent.get("mc"), "umur_jam": None, "skor": None,
                "risiko": {"putusan": "TIDAK-DIKETAHUI", "flag": []},
                "sumber": "pumpfun-riset"}
    st = _tick_state().get(mint) or {}
    tr = _tracker().get(mint) or {}
    mc = st.get("mc") or koin.get("mc") or 0
    liq = koin.get("liq") or 0
    umur = st.get("created") and (time.time() - st["created"]) / 3600 or koin.get("umur_jam")
    putusan_risiko = (koin.get("risiko") or {}).get("putusan", "TIDAK-DIKETAHUI")
    flag_risiko = (koin.get("risiko") or {}).get("flag") or []
    tekanan = koin.get("tekanan_beli")
    vol = koin.get("vol24") or 0
    h1 = koin.get("h1") or 0
    h24 = koin.get("h24") or 0
    reply = koin.get("replies") or tr.get("reply") or 0

    skor = 40.0
    kekuatan, hati = [], []

    # 1. Momentum live
    if h1 >= 20:
        skor += 15; kekuatan.append(f"momentum 1 jam kuat (+{h1:.0f}%)")
    elif h1 >= 5:
        skor += 8; kekuatan.append(f"momentum 1 jam positif (+{h1:.0f}%)")
    elif h1 < -15:
        skor -= 12; hati.append(f"turun {abs(h1):.0f}% dalam 1 jam — sedang dijual")

    # 2. Likuiditas vs MC
    rasio_liq = liq / mc if mc else 0
    if rasio_liq >= 0.15:
        skor += 12; kekuatan.append(f"likuiditas sehat ({rasio_liq*100:.0f}% dari MC)")
    elif rasio_liq > 0 and rasio_liq < 0.05:
        skor -= 10; hati.append("likuiditas tipis — sulit keluar posisi")

    # 3. Volume relatif
    if mc and vol / mc >= 1.5:
        skor += 12; kekuatan.append("volume 24j sangat tinggi vs MC — perhatian pasar besar")
    elif mc and vol / mc >= 0.5:
        skor += 6; kekuatan.append("volume aktif")
    elif mc and vol < mc * 0.05:
        skor -= 6; hati.append("volume sangat rendah — minat melemah")

    # 4. Umur
    if umur is not None:
        if umur < 1:
            skor += 6; kekuatan.append("sangat baru — peluang awal (risiko tinggi)")
        elif umur > 72:
            skor -= 4; hati.append("sudah berumur >3 hari — fase jenuh")

    # 5. Tekanan beli
    if tekanan is not None:
        if tekanan >= 65:
            skor += 10; kekuatan.append(f"tekanan beli dominan ({tekanan}%)")
        elif tekanan <= 40:
            skor -= 8; hati.append(f"tekanan jual lebih besar ({tekanan}%)")

    # 6. Pertumbuhan sejak dianalisa
    mc_awal = tr.get("mc_awal") or 0
    if mc_awal and mc:
        g = mc / mc_awal
        if g >= 2:
            skor += 15; kekuatan.append(f"tumbuh {g:.1f}× sejak dianalisa")
        elif g >= 1.3:
            skor += 8; kekuatan.append(f"naik {(g-1)*100:.0f}% sejak dianalisa")
        elif g < 0.7:
            skor -= 12; hati.append(f"turun {(1-g)*100:.0f}% dari saat dianalisa")

    # 7. Risiko
    if putusan_risiko == "AMAN-RELATIF":
        skor += 10; kekuatan.append("lolos pemeriksaan kontrak (honeypot/bundler bersih)")
    elif putusan_risiko == "HATI-HATI":
        skor -= 6; hati.append("ada catatan risiko kontrak — pakai posisi kecil")
    elif putusan_risiko in ("BAHAYA", "SCAM"):
        skor -= 40; hati.append("TERDETEKSI RISIKO TINGGI/SCAM — hindari")

    # 8. Sosial
    if reply >= 50:
        skor += 6; kekuatan.append(f"komunitas ramai ({reply} komentar)")

    skor = max(0, min(100, round(skor, 1)))
    if skor >= 75: putusan = "SANGAT POTENSIAL"
    elif skor >= 60: putusan = "POTENSIAL"
    elif skor >= 45: putusan = "NETRAL — TUNGGU"
    elif skor >= 30: putusan = "HATI-HATI"
    else: putusan = "HINDARI"

    # narasi
    bagian = []
    bagian.append(f"{koin.get('simbol','?')} saat ini MC ${mc:,.0f}" + (f", umur {umur:.1f} jam" if umur is not None else ""))
    if kekuatan:
        bagian.append("Poin kuat: " + "; ".join(kekuatan[:3]) + ".")
    if hati:
        bagian.append("Perhatian: " + "; ".join(hati[:3]) + ".")
    bagian.append(f"Kesimpulan AI: {putusan} (skor {skor}/100). Ini analisa otomatis, bukan saran finansial — selalu DYOR.")
    return {
        "mint": mint, "simbol": koin.get("simbol"), "nama": koin.get("nama"),
        "skor_ai": skor, "putusan": putusan, "kategori": kategori,
        "kekuatan": kekuatan, "hati_hati": hati,
        "mc": round(mc), "narasi": " ".join(bagian),
        "ts": time.time(),
    }

if __name__ == "__main__":
    import sys
    a = analisa_mint(sys.argv[1])
    print(json.dumps(a, indent=1, ensure_ascii=False))
