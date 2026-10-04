"""proyek.py — info proyek koin: deskripsi, website/social, banner.
Sumber: metadata IPFS pump.fun (description, twitter/telegram/website)
+ DexScreener info (websites/socials/header). Cache permanen data/proyek_map.json."""
import json, os, re, time, urllib.request

MAP_PATH = os.path.join(os.path.dirname(__file__), "data", "proyek_map.json")
_UA = {"User-Agent": "Mozilla/5.0"}

def _muat():
    try:
        with open(MAP_PATH) as f:
            return json.load(f)
    except Exception:
        return {}

def _simpan(m):
    try:
        with open(MAP_PATH, "w") as f:
            json.dump(m, f, ensure_ascii=False)
    except Exception:
        pass

def _get_json(url, timeout=12):
    req = urllib.request.Request(url, headers=_UA)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())

def _bersih(t):
    t = re.sub(r"\s+", " ", (t or "")).strip()
    return t[:500]

def info_proyek(mint, metadata_uri=None, ds_info=None):
    """Kembalikan dict proyek: deskripsi, website, twitter, telegram, banner."""
    m = _muat()
    if mint in m and time.time() - m[mint].get("ts", 0) < 86400 * 7:
        return m[mint]
    out = {"mint": mint, "deskripsi": "", "website": "", "twitter": "", "telegram": "",
           "banner": "", "ts": time.time()}
    # 1) metadata IPFS pump.fun (paling lengkap utk deskripsi proyek)
    if metadata_uri:
        try:
            d = _get_json(metadata_uri)
            out["deskripsi"] = _bersih(d.get("description"))
            out["twitter"] = (d.get("twitter") or "").strip()
            out["telegram"] = (d.get("telegram") or "").strip()
            out["website"] = (d.get("website") or "").strip()
        except Exception:
            pass
    # 1b) fallback: ambil metadata_uri dari pump.fun API (1 mint)
    if not (out["deskripsi"] or out["twitter"] or out["website"]):
        try:
            d = _get_json(f"https://frontend-api-v3.pump.fun/coins?include-nsfw=false&limit=1&query={mint}")
            if isinstance(d, list) and d:
                c = d[0]
                mu = c.get("metadata_uri")
                if mu:
                    md = _get_json(mu)
                    out["deskripsi"] = _bersih(md.get("description"))
                    out["twitter"] = (md.get("twitter") or "").strip()
                    out["telegram"] = (md.get("telegram") or "").strip()
                    out["website"] = (md.get("website") or "").strip()
                if not out["deskripsi"]:
                    out["deskripsi"] = _bersih(c.get("description"))
        except Exception:
            pass
    # 2) DexScreener info (websites/socials/header)
    if ds_info:
        try:
            if not out["deskripsi"]:
                out["deskripsi"] = _bersih(ds_info.get("description"))
            ws = ds_info.get("websites") or []
            if ws and not out["website"]:
                out["website"] = ws[0].get("url", "")
            for soc in ds_info.get("socials") or []:
                tipe = (soc.get("type") or "").lower(); url = soc.get("url", "")
                if "twitter" in tipe or "x.com" in url:
                    out["twitter"] = out["twitter"] or url
                elif "telegram" in tipe or "t.me" in url:
                    out["telegram"] = out["telegram"] or url
            if ds_info.get("header"):
                out["banner"] = ds_info["header"]
        except Exception:
            pass
    # hanya cache bila ada isi (hasil kosong berarti sumber belum tersedia — coba lagi nanti)
    if out["deskripsi"] or out["website"] or out["twitter"] or out["telegram"] or out["banner"]:
        m[mint] = out
        _simpan(m)
    return out
