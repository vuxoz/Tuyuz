# KoinScan — riset & skor koin pump.fun BARU (bonding curve) berbasis PELACAKAN snapshot.
#
# Mengapa pendekatan ini (hasil riset):
#   • Feed `created_timestamp` pump.fun hanya memuat koin umur <10 menit; mayoritas MC $3-5K
#     dan tidak sempat "naik" saat dipotret → skor sesaat tidak bermakna.
#   • Field resmi `ath_market_cap` memungkinkan ukur kenaikan puncak vs sekarang (drop dari ATH).
#   • `last_trade_timestamp` mendeteksi koin yang masih diperdagangkan vs sudah mati.
#   • Yang benar-benar membedakan koin layak: KONSISTENSI NAIK antar poll 10 menit
#     (bukan MC sesaat), volume sosial, kecepatan menuju graduation, dan riwayat creator.
#
# Metrik riset (semua terverifikasi tersedia dari API resmi pump.fun):
#   1. mc_growth_x     = MC sekarang / MC saat pertama terlihat   → apakah benar tumbuh
#   2. laju_mc_per_jam = (MC_now - MC_awal) / jam terlacak        → kecepatan
#   3. pegang_ath_pct  = MC / ATH                                 → masih dekat puncak (kuat) atau sudah dump
#   4. aktif_terakhir  = menit sejak trade terakhir               → hidup atau mati
#   5. konsisten_poll  = berapa poll berturut MC tidak turun      → bukan spike sesaat
#   6. progres_curve   = MC / ~$69K                               → kedekatan graduation
#   7. reply_count     = aktivitas sosial di pump.fun
#   8. creator_serial  = berapa koin dibuat creator ini (deteksi spammer serial)
import json, os, time

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
TRACK_FILE = os.path.join(DATA, "pump_tracker.json")
CREATOR_FILE = os.path.join(DATA, "creator_repo.json")
GRAD_MC = 69_000          # ambang MC graduation pump.fun (perkiraan resmi)
MAKS_SIMPAN = 800         # batas mint terlacak (yang terlama dibuang)


def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, ensure_ascii=False)


def lacak(semua_koin):
    """Perbarui tracker dengan snapshot poll ini. semua_koin: list dict pump.fun mentah."""
    tr = _load(TRACK_FILE, {})
    now = time.time()
    for c in semua_koin:
        mint = c.get("mint")
        if not mint:
            continue
        mc = float(c.get("usd_market_cap") or 0)
        ent = tr.get(mint)
        if not ent:
            tr[mint] = {
                "simbol": c.get("symbol", "?"),
                "nama": (c.get("name") or "?")[:20],
                "mint": mint,
                "img": (c.get("image_uri") or "").strip(),
                "metadata_uri": (c.get("metadata_uri") or "").strip(),
                "creator": c.get("creator", ""),
                "dibuat_api": c.get("created_timestamp", 0) / 1000,
                "pertama_dilihat": now,
                "mc_awal": mc,
                "mc": mc,
                "mc_riwayat": [mc],
                "ath_mc": float(c.get("ath_market_cap") or mc),
                "reply": int(c.get("reply_count") or 0),
                "last_trade": (c.get("last_trade_timestamp") or 0) / 1000,
                "live": bool(c.get("is_currently_live")),
                "poll": 1,
                "konsisten": 0,
                "complete": bool(c.get("complete")),
            }
        else:
            prev = ent["mc"]
            ent["mc"] = mc
            ent["mc_riwayat"] = (ent.get("mc_riwayat") or [])[-9:] + [mc]
            ent["ath_mc"] = max(ent.get("ath_mc") or mc,
                                float(c.get("ath_market_cap") or mc), mc)
            ent["reply"] = int(c.get("reply_count") or 0)
            ent["last_trade"] = (c.get("last_trade_timestamp") or 0) / 1000
            ent["live"] = bool(c.get("is_currently_live"))
            ent["complete"] = bool(c.get("complete"))
            ent["poll"] = ent.get("poll", 1) + 1
            # konsistensi: berapa poll berturut MC naik
            ent["konsisten"] = (ent.get("konsisten", 0) + 1) if mc > prev else 0
    # buang yang paling lama bila melebihi batas
    if len(tr) > MAKS_SIMPAN:
        urut = sorted(tr.items(), key=lambda kv: kv[1].get("pertama_dilihat", 0))
        for mint, _ in urut[:len(tr) - MAKS_SIMPAN]:
            del tr[mint]
    _save(TRACK_FILE, tr)
    return tr


def catat_creator(pump_map):
    """Repo creator → berapa koin dibuat (deteksi serial spammer/rugger)."""
    repo = _load(CREATOR_FILE, {})
    for c in pump_map:
        cr = c.get("creator")
        if not cr:
            continue
        e = repo.setdefault(cr, {"koin": [], "komplit": 0})
        mint = c.get("mint")
        if mint and mint not in e["koin"]:
            e["koin"].append(mint)
            e["koin"] = e["koin"][-50:]
        if c.get("complete"):
            e["komplit"] = e.get("komplit", 0) + 0  # dihitung ulang dari repo saat skor
    _save(CREATOR_FILE, repo)
    return repo


def nilai(ent, repo=None):
    """Skor koin pump.fun baru 0-100 berbasis RISET pelacakan. Return (skor, alasan[]).
    Baseline: koin baru lahir (belum ada bukti) mulai dari ~35 — bukan 0.
    Skor TURUN bila muncul bukti negatif (dump, mati, mandek), NAIK bila bukti positif."""
    s = 35.0  # baseline koin baru netral
    alasan = []
    now = time.time()
    mc = ent.get("mc") or 0
    mc_awal = ent.get("mc_awal") or 1
    umur_jam = max((now - ent.get("pertama_dilihat", now)) / 3600, 0.001)

    # 1. PERTUMBUHAN NYATA (±30): MC sekarang vs saat pertama terlihat
    growth = mc / mc_awal if mc_awal else 1
    if growth >= 5:
        s += 30; alasan.append(f"tumbuh {growth:.1f}× sejak terpantau")
    elif growth >= 2:
        s += 22; alasan.append(f"tumbuh {growth:.1f}× sejak terpantau")
    elif growth >= 1.3:
        s += 14; alasan.append(f"naik {growth:.1f}×")
    elif growth < 0.8:
        s -= 18; alasan.append(f"turun {(1-growth)*100:.0f}% dari pantauan awal")

    # 2. KECEPATAN (0-15): dolar MC per jam
    laju = (mc - mc_awal) / umur_jam
    if laju > 200_000:
        s += 15; alasan.append("laju sangat cepat")
    elif laju > 50_000:
        s += 10; alasan.append("laju cepat")
    elif laju > 10_000:
        s += 5

    # 3. POSISI TERHADAP ATH (0-15): masih dekat puncak = minat kuat
    ath = ent.get("ath_mc") or mc
    rasio_ath = mc / ath if ath else 0
    if rasio_ath >= 0.85:
        s += 15; alasan.append("masih dekat puncak ATH")
    elif rasio_ath >= 0.6:
        s += 8
    elif rasio_ath < 0.35:
        s -= 12; alasan.append(f"jauh di bawah ATH (-{(1-rasio_ath)*100:.0f}%)")

    # 4. MASIH DIPERDAGANGKAN (0-15): hindari koin mati
    menit_lalu = (now - ent.get("last_trade", 0)) / 60 if ent.get("last_trade") else 9999
    if menit_lalu <= 3:
        s += 15; alasan.append("aktif ditransaksikan")
    elif menit_lalu <= 10:
        s += 9
    elif menit_lalu <= 30:
        s += 3
    else:
        s -= 15; alasan.append(f"tidak ada trade {menit_lalu:.0f} menit")

    # 5. KONSISTENSI (0-10): naik berturut-turut antar poll
    k = ent.get("konsisten", 0)
    if k >= 3:
        s += 10; alasan.append(f"naik konsisten {k} poll")
    elif k == 2:
        s += 6
    elif k == 1:
        s += 2

    # 6. PROGRES MENUJU GRADUATION (0-10)
    prog = mc / GRAD_MC
    if 0.5 <= prog < 1:
        s += 10; alasan.append(f"{prog*100:.0f}% menuju graduation")
    elif 0.2 <= prog < 0.5:
        s += 6
    elif prog >= 1 or ent.get("complete"):
        s += 12; alasan.append("sudah/baru graduated")

    # 7. SOSIAL (0-5)
    rep = ent.get("reply", 0)
    if rep >= 20:
        s += 5; alasan.append(f"{rep} komentar")
    elif rep >= 5:
        s += 3

    # 8. RIWAYAT CREATOR (penalti): creator serial spam (banyak koin, jarang lulus)
    if repo:
        e = repo.get(ent.get("creator"), {})
        jum = len(e.get("koin", []))
        if jum >= 50:
            s -= 15; alasan.append(f"creator sudah buat {jum} koin (spammer serial)")
        elif jum >= 20:
            s -= 8; alasan.append(f"creator buat {jum} koin")

    # 8b. MC TERLALU KECIL (penalti): koin <$4K sangat mudah dimanipulasi dev
    if mc < 4_000 and umur_jam < 6:
        s -= 10; alasan.append("MC terlalu kecil <$4K (risiko manipulasi tinggi)")
    elif mc < 8_000 and umur_jam < 1:
        s -= 4; alasan.append("MC sangat kecil — tunggu bukti pertumbuhan")

    # 9. BONUS LIVE STREAM (0-5) + penalti umur ekstrem (>3 hari masih di curve = gagal)
    if ent.get("live"):
        s += 5; alasan.append("sedang livestream")
    umur_total_h = (now - (ent.get("dibuat_api") or ent.get("pertama_dilihat", now))) / 3600
    if umur_total_h > 72 and not ent.get("complete"):
        s -= 20; alasan.append("mandek >3 hari di bonding curve")

    return round(max(0, min(100, s)), 1), alasan


def kandidat_layak(min_skor=55, min_poll=2, maks_umur_jam=72):
    """Koin pump.fun baru (umur <= maks_umur_jam) yang terlacak cukup lama & skornya tinggi.
    JALUR CEPAT: koin dengan pertumbuhan riil >=1.5x sejak pertama terpantau masuk walau
    baru 1 poll — jangan sampai koin yang meledak cepat terlewat menunggu poll berikutnya."""
    tr = _load(TRACK_FILE, {})
    repo = _load(CREATOR_FILE, {})
    now = time.time()
    hasil = []
    for mint, ent in tr.items():
        if ent.get("complete"):
            continue
        if ent.get("poll", 0) < min_poll:
            growth_riil = (ent.get("mc") or 0) / (ent.get("mc_awal") or 1)
            if not (growth_riil >= 1.5 and (ent.get("mc") or 0) >= 15_000):
                continue  # belum 2 poll & belum bukti ledakan → tunggu
        # hanya koin yang BENAR-BENAR baru (dibuat ≤ 72 jam lalu)
        umur = (now - (ent.get("dibuat_api") or ent.get("pertama_dilihat", now))) / 3600
        if umur > maks_umur_jam:
            continue
        skor, alasan = nilai(ent, repo)
        if skor >= min_skor:
            now = time.time()
            hasil.append({
                "simbol": ent["simbol"], "nama": ent.get("nama", "?"),
                "mint": mint, "sumber": "pumpfun-riset",
                "mc": ent["mc"], "ath_mc": ent.get("ath_mc", ent["mc"]),
                "umur_jam": round((now - ent.get("pertama_dilihat", now)) / 3600, 1),
                "reply": ent.get("reply", 0),
                "img": ent.get("img", ""),
                "growth": round(ent["mc"] / (ent.get("mc_awal") or 1), 2),
                "pegang_ath": round((ent["mc"] / ent["ath_mc"]) * 100) if ent.get("ath_mc") else 0,
                "konsisten": ent.get("konsisten", 0),
                "poll": ent.get("poll", 0),
                "skor": skor, "alasan": alasan,
                "url": f"https://pump.fun/coin/{mint}",
            })
    return sorted(hasil, key=lambda k: -k["skor"])
