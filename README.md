# KoinScan — Deploy di Railway

KoinScan = pemindai meme coin real-time (Solana + multi-chain). Versi ini **versi real-time penuh**: tick 20 detik, analisa cepat 60 detik, scan berat 10 menit, snapshot harga multi-chain otomatis → grafik koin tumbuh sendiri.

**Tanpa dependency** — Python 3.11 stdlib saja. Tidak perlu `pip install` apa pun.

---

## Cara Deploy (paling mudah — lewat GitHub)

1. **Buat akun** di [railway.com](https://railway.com) (login pakai GitHub — gratis $5 kredit/bulan)

2. **Upload kode ke GitHub**
   - Buat repo baru, mis. `koinscan` (Private juga boleh)
   - Upload **SEMUA isi folder ini** (file `.py`, folder `static/`, folder `data/`, `railway.toml`, `nixpacks.toml`, `Procfile`, README)

3. **Deploy**
   - Buka [railway.com/new](https://railway.com/new) → **Deploy from GitHub repo** → pilih repo `koinscan`
   - Railway otomatis mendeteksi Python (via `nixpacks.toml`) dan menjalankan `python3 web_server.py`
   - Tunggu build ±1–2 menit

4. **Buka ke publik (PENTING — wajib)**
   - Masuk ke service kamu → tab **Settings** → **Networking** → **Generate Domain**
   - Railway memberi URL seperti `https://koinscan.up.railway.app`
   - Port otomatis: aplikasi membaca env `PORT` dari Railway (sudah didukung `web_server.py`)

5. **Verifikasi**
   - `https://NAMA.up.railway.app/` → beranda
   - `https://NAMA.up.railway.app/api/feed` → JSON koin = backend hidup

---

## Cara Deploy via CLI (alternatif)

```bash
npm i -g @railway/cli
railway login
cd koinscan            # folder ini
railway init           # buat proyek baru
railway up             # deploy
railway domain         # generate domain publik
```

---

## Catatan penting

- **Data tidak persisten antar-restart** (filesystem container sementara). Snapshot grafik/riwayat terbentuk ulang otomatis setelah beberapa menit berjalan. Kalau mau persisten, tambahkan **Volume** di Railway: Settings → Volumes → mount ke `/app/data` (folder `data/`).
- Railway hobby = $5 kredit gratis/bulan; layanan ini sangat hemat (±1 vCPU, <100MB RAM) — kemungkinan besar **gratis total**.
- Semua API eksternal (pump.fun, DexScreener, GeckoTerminal, RugCheck) dipanggil langsung dari server Railway — IP server-nya bersih, tidak seperti browser.
- Ukuran kecil (±150KB) — deploy cepat.

---

## Struktur file

```
├── web_server.py      ← server web + thread real-time (titik masuk)
├── tick.py            ← tick harga 20 detik
├── scanner.py         ← scan berat semua sumber + RugCheck
├── analisa_cepat.py   ← skor ulang 60 detik
├── analisa_ai.py      ← skor AI 8 faktor
├── multichain.py      ← Ethereum/BSC/Base/TON/Arbitrum/Polygon
├── risiko.py          ← honeypot/bundler/rug
├── pump_riset.py, proyek.py, backfill.py
├── static/            ← frontend (13 halaman)
└── data/              ← state (dibuat/diisi otomatis)
```

KoinScan by **arifrfza**
