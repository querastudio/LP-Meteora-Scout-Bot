# LP Scout — Meteora DLMM (Solana)

Bot Telegram yang **hanya memindai dan merekomendasikan** pool Meteora DLMM untuk strategi LP
single-sided SOL (Bid-Ask, range -70%). Bot tidak memegang private key dan tidak membuat transaksi.

## Cara kerja

1. Ambil daftar pool (`dlmm.datapi.meteora.ag/pools`, 6 halaman × 50, urut volume 24 jam).
2. **Penyaringan murah**: SOL di salah satu sisi, `bin_step ≥ 80`, TVL ≥ $10.000, bukan blacklist,
   bukan aset besar/stablecoin (daftar bisa diubah lewat `EXCLUDED_SYMBOLS`). Ambil 20 dengan Fee/TVL tertinggi.
3. Untuk 20 kandidat: candle 5 menit 24 jam (3 jendela × 8 jam) → 15 menit → metrik → label.
4. Pool yang mendapat label dicek keamanannya. Pool yang pernah aktif selalu dihitung ulang
   walau sudah keluar dari 20 besar, supaya penurunannya terdeteksi.

### Metrik (modul murni `lpscout/metrics.py`)

| Metrik | Rumus |
|---|---|
| feeYield | (fees24h − protocol_fees24h) / TVL |
| σ harian | stdev(log return close 15m) × √96 |
| LVR | σ² / 8 |
| net edge | feeYield − LVR · fee/LVR = feeYield / LVR |
| aktivitas | candle 15m dengan volume > 0 / 96 |
| konsentrasi | volume candle 15m terbesar / volume 24 jam |
| laju 6j | volume 6 jam terakhir × 4 / volume 24 jam |

"Bad print" (close menyimpang > 70% dari **kedua** tetangga) diganti rata-rata tetangga.
Data < 16 candle 15m → semua metrik berbasis candle `null` (tampil `n/a`, bukan 0).

### Label (nilai dari backtest 211 pool; bisa diubah lewat `/set` atau env)

| Label | Syarat | Ukuran |
|---|---|---|
| ⭐ ideal | feeYield ≥ 20%, net edge ≥ 10%, aktivitas ≥ 90%, konsentrasi < 10% | 100% |
| ✅✅ bagus | feeYield ≥ 10%, net edge ≥ 5%, aktivitas ≥ 90%, konsentrasi < 10%, laju 6j ≥ 50% | 75% |
| ✅ minimal | feeYield ≥ 5%, net edge ≥ 2%, aktivitas ≥ 90%, konsentrasi < 10%, laju 6j ≥ 50% | 50% |
| ❌ tolak | selain itu (syarat yang kurang disimpan dan ditampilkan) | – |

### Keamanan (terpisah dari label)

Mint authority dan freeze authority harus dicabut, dan top-10 holder < 30% (pemilik off-curve/PDA
seperti pool & vault diabaikan; akun milik satu pemilik dijumlahkan). Gagal → status **risiko**
dan pool **tidak pernah direkomendasikan**, apa pun labelnya. Tidak bisa dicek → **belum terverifikasi**
(tetap dilaporkan, tapi ditandai). RugCheck hanya catatan tambahan; kegagalannya tidak memblokir.

## Perintah Telegram (hanya `TELEGRAM_OWNER_ID`; yang lain diabaikan diam-diam)

| Perintah | Fungsi |
|---|---|
| `/scan` | Pindai sekarang (tidak memicu alert, agar alert terjadwal tidak terlewat) |
| `/top` | Hasil scan terakhir |
| `/pool <alamat>` | Detail satu pool, termasuk syarat yang kurang dan hasil penyaringan awal |
| `/set` · `/set <nama> <nilai>` | Lihat / ubah ambang (disimpan di SQLite, berlaku juga setelah restart) |
| `/status` | Scan terakhir, jumlah pool, sumber data yang gagal, jadwal berikutnya |
| `/help` | Bantuan |

Setiap perintah dibatasi 25 detik: bila lebih lama, bot membalas "masih memproses" lalu mengirim
hasilnya setelah selesai. Scan otomatis tiap `SCAN_MINUTES` (15). Alert dikirim **hanya** untuk pool yang
baru naik ke minimal/bagus/ideal atau naik label, cooldown 2 jam per pool; pool yang turun ke tolak
dikeluarkan dari daftar aktif dan diberitahukan sekali.

## Menjalankan

Butuh proses yang **berjalan terus** (long-poll Telegram + scheduler + SQLite), bukan job cron.

```bash
cp .env.example .env     # isi TELEGRAM_BOT_TOKEN dan TELEGRAM_OWNER_ID (RPC_URL pribadi disarankan)
```

**Docker (disarankan)**
```bash
docker compose up -d --build && docker compose logs -f
```
Database ada di volume `lpscout-data`.

**Tanpa Docker / systemd**
```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
set -a; . ./.env; set +a; .venv/bin/python -m lpscout
```
Unit systemd: `ExecStart=/opt/lpscout/.venv/bin/python -m lpscout`, `EnvironmentFile=/opt/lpscout/.env`,
`WorkingDirectory=/opt/lpscout`, `Restart=always`.

> Workflow GitHub Actions cron versi lama sudah dihapus (job Actions tidak bisa menjalankan bot
> yang hidup terus). Actions kini hanya menjalankan CI. Hentikan pinger cron-job.org lama bila masih ada.

## Pengembangan

```bash
pip install -r requirements.txt -r requirements-dev.txt
ruff check lpscout tests && mypy && pytest -q
```

Struktur: `lpscout/metrics.py`, `labels.py`, `alerts.py` (murni) · `sources/` (Meteora, keamanan) ·
`http.py` (timeout/retry/cache) · `scanner.py` · `store.py` (SQLite) · `formatter.py` · `bot.py` · `telegram.py`.
Fixture payload Meteora asli ada di `tests/fixtures/`.

## Asumsi dan keterbatasan

- Volume 24 jam untuk konsentrasi/laju 6j memakai **jumlah volume candle** (konsisten dengan pembilangnya),
  bukan field `volume.24h` pool. σ memakai simpangan baku sampel.
- Setiap candle 15m yang tidak ada dianggap tanpa volume; return dihitung antar candle yang ada.
- `getTokenLargestAccounts` hanya mengembalikan 20 akun terbesar; setelah PDA dibuang bisa tersisa < 10
  pemilik, sehingga top-10% adalah batas bawah. RPC publik sering membatasi metode ini — pakai `RPC_URL` pribadi.
- Hasil keamanan di-cache 6 jam; scan gagal sebagian dicatat di `/status`.
