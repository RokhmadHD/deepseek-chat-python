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
- Env auth dari browser/capture, biasanya `DEEPSEEK_BEARER` dan cookie.
- Network access untuk install dependency dan download wasm PoW pertama kali.

## Setup

```bash
cd ~/deepseek-chat-python
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
cp .env.example .env
```

Lalu isi `.env`.

Minimal yang biasanya perlu:

```env
DEEPSEEK_BEARER=isi_token_bearer
DEEPSEEK_COOKIE_HEADER=isi_cookie_header_lengkap
```

Kalau tidak mau taruh cookie panjang langsung di `.env`, pakai file:

```env
DEEPSEEK_COOKIE_FILE=/path/ke/cookie.txt
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

## Konfigurasi

Env penting:

| Env | Default | Keterangan |
| --- | --- | --- |
| `DEEPSEEK_BEARER` | kosong | Bearer token dari DeepSeek web. |
| `DEEPSEEK_COOKIE_HEADER` | kosong | Cookie header lengkap dari browser. |
| `DEEPSEEK_COOKIE_FILE` | kosong | File berisi cookie header. |
| `DEEPSEEK_API_BASE` | `https://chat.deepseek.com` | Base URL DeepSeek web. |
| `DEEPSEEK_MODEL_TYPE` | `default` | Model type yang dikirim ke DeepSeek. |
| `DEEPSEEK_SEARCH_ENABLED` | `true` | Aktifkan search di request chat. |
| `DEEPSEEK_THINKING_ENABLED` | `false` | Aktifkan thinking mode. |
| `DEEPSEEK_PREEMPT` | `false` | Nilai `preempt` request. |
| `DEEPSEEK_POW_WASM_CACHE` | `.cache/sha3_wasm_bg.7b9ca65ddd.wasm` | Lokasi cache wasm PoW. |

Lihat [.env.example](./.env.example) untuk daftar lengkap.

## Troubleshooting

Jika dapat `401` atau `403`, auth/cookie kemungkinan sudah expired atau tidak lengkap. Ambil ulang session dari browser.

Jika error saat download wasm, cek network lalu ulangi command. File wasm akan dicache di `.cache/`.

Jika command `deepseek-chat` tidak ditemukan, pastikan virtualenv aktif dan `pip install -e .` sudah berhasil.

## Status

Versi ini adalah port awal untuk chat biasa. Bagian parser dari project lama sengaja ditinggalkan dulu supaya fondasi client lebih sederhana dan mudah dites.
