# KoinScan — modul analisa risiko: honeypot, bundler, rug, scam (Solana)
# Sumber: RugCheck API (report penuh per token). Cache per-mint agar hemat rate-limit.
import json, os, time, urllib.request, urllib.error

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
os.makedirs(DATA, exist_ok=True)
RISK_CACHE = os.path.join(DATA, "risiko.json")
TTL_RISIKO = 6 * 3600  # laporan risiko berlaku 6 jam

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _load():
    try:
        with open(RISK_CACHE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(db):
    with open(RISK_CACHE, "w") as f:
        json.dump(db, f)


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers=HEADERS)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def analisa_mint(mint):
    """Return dict risiko untuk satu mint. None jika gagal."""
    db = _load()
    ent = db.get(mint)
    if ent and time.time() - ent["ts"] < TTL_RISIKO:
        return ent["data"]
    try:
        r = _get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report")
    except Exception as e:
        print("rugcheck err", mint[:8], e)
        return ent["data"] if ent else None

    risks = r.get("risks") or []
    kritis = [x for x in risks if x.get("level") in ("danger", "critical")]
    peringatan = [x for x in risks if x.get("level") == "warn"]

    th = r.get("topHolders") or []
    top10_pct = sum(h.get("pct", 0) for h in th[:10])
    # insider: wallet terkait creator yang pegang supply besar
    insiders = r.get("insiders") or []
    insider_pct = sum(i.get("pct", 0) for i in insiders if i.get("pct"))

    # ---- deteksi tiap pola scam ----
    flag = []

    # 1. Honeypot: mint/freeze authority aktif = pembuat bisa cetak tak terbatas / bekukan wallet
    if r.get("mintAuthority"):
        flag.append(("HONEYPOT-MINT", "critical",
                     "Mint authority aktif — pembuat bisa mencetak token tak terbatas"))
    if r.get("freezeAuthority"):
        flag.append(("HONEYPOT-FREEZE", "critical",
                     "Freeze authority aktif — pembuat bisa membekukan wallet pembeli"))

    # 2. Sudah rug
    if r.get("rugged"):
        flag.append(("RUGGED", "critical", "Terdeteksi sudah pernah rug/kempretin"))

    # 3. Transfer fee (pajak jual ekstrem)
    tf = r.get("transferFee")
    if tf and _pct(tf) > 10:
        flag.append(("PAJAK-TINGGI", "danger", f"Transfer fee {_pct(tf):.0f}% — honeypot jual"))

    # 4. Bundler: top-10 holder pegang sangat besar + holder sedikit = bundler/sybil
    jumlah_holder = r.get("totalHolders") or 0
    if jumlah_holder and top10_pct > 45 and jumlah_holder < 500:
        flag.append(("BUNDLER", "danger",
                     f"Top-10 holder pegang {top10_pct:.0f}% dari hanya {jumlah_holder} holder — indikasi bundler"))
    elif top10_pct > 60:
        flag.append(("KONSENTRASI-TINGGI", "warn",
                     f"Top-10 holder pegang {top10_pct:.0f}% supply"))

    # 5. Insider network
    if insider_pct > 15:
        flag.append(("INSIDER", "danger",
                     f"Wallet insider (terkait creator) pegang {insider_pct:.0f}% supply"))
    if r.get("graphInsidersDetected"):
        flag.append(("INSIDER-NETWORK", "warn", "Jaringan insider terdeteksi pada graf transfer"))

    # 6. LP tidak terkunci (koin DEX; bonding curve pump.fun tidak punya LP terpisah)
    lp = r.get("lpLockedPct")
    token_type = r.get("tokenType", "")
    if lp is not None and token_type and token_type.lower() != "pump_amm":
        pass  # lpLockedPct dari summary; detail LP ada di markets — gunakan risks RugCheck saja
    for x in kritis:
        nama = x.get("name", "").lower()
        if "lock" in nama and "lp" in nama:
            flag.append(("LP-TIDAK-TERKUNCI", "danger", x.get("description", "LP tidak terkunci")))
        if "low liquidity" in nama or "low amount" in nama:
            flag.append(("LIKUIDITAS-RENDAH", "warn", x.get("description", "")))

    # ---- putusan akhir ----
    skor_risiko = r.get("score") or 0  # RugCheck: makin TINGGI makin BERISIKO
    lvls = {f[1] for f in flag}
    is_bonding = token_type.lower() == "pump_amm" or (mint or "").endswith("pump")
    # Untuk koin bonding curve pump.fun: BUNDLER & konsentrasi awal adalah NORMAL
    # (creator+sniper beli di detik pertama). Flag danger yang berasal khusus dari
    # pola awal peluncuran tidak otomatis jadi BAHAYA — cukup HATI-HATI.
    flag_danger_normal_curve = {"BUNDLER", "KONSENTRASI-TINGGI"}
    danger_benar = any(f[1] == "danger" and f[0] not in flag_danger_normal_curve for f in flag)
    if "critical" in lvls or r.get("rugged"):
        putusan = "SCAM"
    elif is_bonding and not danger_benar and skor_risiko <= 2000:
        # koin curve: hanya SCAM/critical yang mematikan; sisanya HATI-HATI (transparan di flag)
        putusan = "HATI-HATI" if flag else "AMAN-RELATIF"
    elif danger_benar or skor_risiko > 2000 or len(kritis) >= 2:
        putusan = "BAHAYA"
    elif len(flag) >= 2 or len(peringatan) >= 3:
        putusan = "HATI-HATI"
    else:
        putusan = "AMAN-RELATIF"

    data = {
        "putusan": putusan,
        "skor_rugcheck": skor_risiko,
        "flag": [{"tipe": t, "level": lv, "ket": k} for t, lv, k in flag],
        "peringatan": [x.get("name") for x in peringatan][:5],
        "top10_pct": round(top10_pct, 1),
        "jumlah_holder": jumlah_holder,
        "insider_pct": round(insider_pct, 1),
        "lp_locked_pct": lp,
        "token_type": token_type,
    }
    db[mint] = {"ts": time.time(), "data": data}
    _save(db)
    return data


def _pct(tf):
    try:
        v = tf
        if isinstance(v, dict):
            v = v.get("pct") or v.get("percent") or 0
        return float(v) * (100 if float(v) <= 1 else 1)
    except (TypeError, ValueError):
        return 0


def layak_beli(risiko, min_putusan="HATI-HATI"):
    """Filter: hanya koin dengan risiko dapat diterima."""
    urutan = ["AMAN-RELATIF", "HATI-HATI", "BAHAYA", "SCAM"]
    if risiko is None:
        return True  # data belum ada → jangan blokir, hanya tandai "belum diperiksa"
    return urutan.index(risiko.get("putusan", "SCAM")) <= urutan.index(min_putusan)
