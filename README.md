# deepseek-chat-python

Client Python minimal untuk chat biasa ke DeepSeek web.

Project ini sengaja dibuat kecil dulu: belum ada parser, belum ada OpenAI-compatible server, belum ada tool-calling. Fokusnya hanya bisa kirim prompt ke DeepSeek web dan print jawaban teks.

## Fitur

- Membuat chat session baru lewat `/api/v0/chat_session/create`.
- Mengambil PoW challenge lewat `/api/v0/chat/create_pow_challenge`.
- Solve PoW dengan wasm resmi DeepSeek.
- Mengirim prompt ke `/api/v0/chat/completion`.
- Parse response SSE DeepSeek menjadi teks biasa.
- Bisa dipakai sekali jalan atau mode interaktif.

## Kebutuhan

- Python 3.11 atau lebih baru.
- Session DeepSeek web yang masih valid.
- Network access untuk install dependency dan download wasm PoW pertama kali.

## Setup

```bash
cd ~/deepseek-chat-python
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
cp .env.example .env
```

`.env` hanya untuk config non-secret. Token dan cookie login disimpan ke SQLite.

Login:

```bash
deepseek-chat-login
```

Command ini membuka browser, tunggu kamu login ke DeepSeek web, lalu menyimpan capture ke `captures/` dan auth ke `.data/session.db`. Kalau login ulang, profile yang sama akan di-replace. Secara default command ini memakai Camoufox di `/home/tensanq/.cache/camoufox/camoufox` kalau binary itu ada.

Kalau mau paksa path Camoufox tertentu:

```bash
CAMOUFOX_BIN=/home/tensanq/.cache/camoufox/camoufox deepseek-chat-login
```

Kalau auto-detect login gagal, pakai mode manual:

```bash
deepseek-chat-login --manual
```

Profile lain:

```bash
deepseek-chat-login --profile kerja
deepseek-chat --profile kerja "hai bang"
deepseek-chat-tui --profile kerja
```

Kalau belum ada browser Playwright di mesin:

```bash
python3 -m playwright install chromium
```

## Cara Pakai

Sekali jalan:

```bash
deepseek-chat "hai bang"
```

Mode interaktif:

```bash
deepseek-chat
```

Di mode interaktif, session dan `parent_message_id` dipertahankan selama proses masih hidup, jadi percakapan lanjut dalam thread yang sama.

TUI terminal:

```bash
deepseek-chat-tui
```

Kontrol TUI:

- `Enter` untuk kirim pesan.
- `/quit`, `/exit`, atau `/q` untuk keluar.
- `PgUp` dan `PgDn` untuk scroll riwayat chat.

## Konfigurasi

Env penting:

| Env | Default | Keterangan |
| --- | --- | --- |
| `DEEPSEEK_API_BASE` | `https://chat.deepseek.com` | Base URL DeepSeek web. |
| `DEEPSEEK_MODEL_TYPE` | `default` | Model type yang dikirim ke DeepSeek. |
| `DEEPSEEK_SEARCH_ENABLED` | `true` | Aktifkan search di request chat. |
| `DEEPSEEK_THINKING_ENABLED` | `false` | Aktifkan thinking mode. |
| `DEEPSEEK_PREEMPT` | `false` | Nilai `preempt` request. |
| `DEEPSEEK_POW_WASM_CACHE` | `.cache/sha3_wasm_bg.7b9ca65ddd.wasm` | Lokasi cache wasm PoW. |

Auth login disimpan di `.data/session.db` dan tidak masuk git.

## Troubleshooting

Jika dapat `401` atau `403`, auth/cookie kemungkinan sudah expired atau tidak lengkap. Jalankan `deepseek-chat-login` lagi untuk replace session SQLite.

Jika error saat download wasm, cek network lalu ulangi command. File wasm akan dicache di `.cache/`.

Jika command `deepseek-chat` tidak ditemukan, pastikan virtualenv aktif dan `pip install -e .` sudah berhasil.

Jika `deepseek-chat-login` gagal membuka browser, pastikan Camoufox masih ada di `/home/tensanq/.cache/camoufox/camoufox`, atau set `CAMOUFOX_BIN=/path/to/camoufox`. Fallback terakhir: install browser Playwright dengan `python3 -m playwright install chromium`.

## Status

Versi ini adalah port awal untuk chat biasa. Bagian parser dari project lama sengaja ditinggalkan dulu supaya fondasi client lebih sederhana dan mudah dites.
