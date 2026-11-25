# kitaptakip

Okuma ilerlemesini, rafları ve yıllık hedefi takip eden Flask uygulaması.

## Kurulum

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python application.py
```

Uygulamaya <http://localhost:5010> adresinden girilir. Kullanıcı: `test`, şifre: `123`.

## Docker

```bat
docker compose up -d --build
```

Uygulama <http://localhost:5010> adresinde çalışır.