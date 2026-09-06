# Leiturgia Pay Backend (owner-side relay)

Holds the PayMongo **live** secret keys so customer machines never see them.

The local Leiturgia server proxies its `/api/pay/*` endpoints here when the
customer's `config.json` sets `paymongo_backend` + `paymongo_backend_token`.

## Local run (test with sandbox keys)

```bat
set PM_SK_TEST=sk_test_...
set PM_PK_TEST=pk_test_...
set PM_BACKEND_AUTH=change-me
set LICENSE_PRICE_PESO=500
pip install -r requirements.txt
python app.py
```

## Endpoints

| Method | Path | Body / Query | Returns |
|--------|------|--------------|---------|
| GET | `/api/health` | — | `{"ok": true, "live": bool}` |
| POST | `/api/pay/create` | `{"hwid": "..."}` + `X-Auth` | `{"ok": true, "id": pi, "qr_image": "...", "test_url": "..."}` |
| GET | `/api/pay/status?id=pi_...` | `X-Auth` | `{"paid": bool, "status": "..."}` |

All `/api/pay/*` calls require header `X-Auth: <PM_BACKEND_AUTH>`.

## Security notes

- Never commit `PM_SK_LIVE`/`PM_PK_LIVE`. Set them as **environment
  variables** in the hosting dashboard (Render: your service → Environment).
- `LICENSE_PRICE_PESO` is set on the backend, so a customer cannot request a
  lower amount from the app.
- The in-memory `_created` list of payment intents resets on restart; the app
  polls within minutes, so this is acceptable. Status is only reported for
  intents created by this backend.

## Deploy to Render (free tier)

1. Push this folder (and repo) to GitHub.
2. Render dashboard → **New → Web Service** → connect the repo.
3. Render auto-detects `render.yaml` (Blueprint) **or** create the service manually:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app --bind 0.0.0.0:10000 --workers 1`
   - **Instance Type:** Free
4. Environment → add:
   - `PM_SK_LIVE` = your `sk_live_...`
   - `PM_PK_LIVE` = your `pk_live_...`
   - `PM_BACKEND_AUTH` = a long random string (also put in the customer
     `config.json` as `paymongo_backend_token`)
   - `LICENSE_PRICE_PESO` = `500`
5. Deploy. Your service URL is like `https://leiturgia-pay-backend.onrender.com`.

Then the customer `config.json`:

```json
{
  "owner_email": "you@example.com",
  "license_price_peso": 500,
  "paymongo_backend": "https://leiturgia-pay-backend.onrender.com",
  "paymongo_backend_token": "<same random string>"
}
```