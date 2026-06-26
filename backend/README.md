# Backend

## Local Transformer Mode

SkillBridge can run its AI features fully in the backend with local transformer models while keeping the existing fallback path.

Current local models:

- Embeddings: `sentence-transformers/all-MiniLM-L6-v2`
- Zero-shot skill filtering: `MoritzLaurer/deberta-v3-base-zeroshot-v1.1-all-33`

If those models are unavailable, the backend automatically falls back to the lighter local hash/rule logic.

## Media Storage Modes

Avatar uploads can run in one of two modes:

- `local`: stores files under `backend/data/uploads/avatars` and serves them from `/media/avatars/...`
- `s3`: uploads files to an S3/R2-compatible bucket using the media environment variables below

## Security Notes

- Authentication endpoints are request-throttled by identity and IP address to reduce credential stuffing and upload abuse.
- Expensive AI routes are throttled per authenticated user and IP address.
- Sessions follow the backend token TTL and are rejected if the stored expiry is missing, malformed, or outside the allowed window.
- Successful admin mutations append audit records to `audit_events` with actor, target, request IP, and action details.
- Rate limiting and audit logs key off the request's real client IP, not the raw socket peer, when running behind a trusted reverse proxy or load balancer. Configure `TRUSTED_PROXY_CIDRS` (see below) so this resolves correctly and isn't spoofable.

## Install

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Optional Environment Variables

```bash
PASSWORD_RESET_TOKEN_TTL_MINUTES=60
LOCAL_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
LOCAL_ZERO_SHOT_MODEL=MoritzLaurer/deberta-v3-base-zeroshot-v1.1-all-33
LOCAL_MODEL_DEVICE=-1
LOCAL_MODEL_PREWARM=true
ADMIN_OWNER_EMAILS=owner@example.com
ADMIN_TEAM_EMAILS=teammate1@example.com,teammate2@example.com
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
STRIPE_PRICE_ID=
STRIPE_PRICE_ID_STARTER=
STRIPE_PRICE_ID_PRO=
STRIPE_PRICE_ID_ELITE=
STRIPE_CURRENCY=usd
STRIPE_SUCCESS_URL=
STRIPE_CANCEL_URL=
STRIPE_BILLING_PORTAL_RETURN_URL=
MEDIA_STORAGE_MODE=local
MEDIA_S3_ENDPOINT_URL=
MEDIA_S3_BUCKET=
MEDIA_S3_REGION=
MEDIA_S3_ACCESS_KEY_ID=
MEDIA_S3_SECRET_ACCESS_KEY=
MEDIA_S3_PUBLIC_BASE_URL=
MEDIA_S3_KEY_PREFIX=avatars
TRUSTED_PROXY_CIDRS=
```

Notes:

- `LOCAL_MODEL_DEVICE=-1` keeps inference on CPU.
- Set `LOCAL_MODEL_DEVICE=0` if you have a CUDA GPU available to the backend.
- `LOCAL_MODEL_PREWARM=true` loads the transformer models on backend startup instead of waiting for the first Job Match or Evidence request.
- `ADMIN_OWNER_EMAILS` bootstraps owner access on registration for the listed emails.
- `ADMIN_TEAM_EMAILS` bootstraps team access on registration for the listed emails.
- `PASSWORD_RESET_TOKEN_TTL_MINUTES` controls how long password reset links remain valid.
- Stripe variables are required when live subscription checkout is enabled.
- `MEDIA_STORAGE_MODE=local` keeps uploads on disk for development.
- `MEDIA_STORAGE_MODE=s3` requires the S3/R2 endpoint, bucket, region, access key, secret key, and a public base URL if the bucket is not already public.
- `TRUSTED_PROXY_CIDRS` is a comma-separated list of CIDR ranges (e.g. `10.0.0.0/8,172.16.0.0/12`) for your reverse proxy or load balancer. Only requests from those ranges have their `X-Forwarded-For`/`X-Real-IP` headers trusted for determining the client's real IP; leave it empty if the backend is reached directly. Don't set it to an overly broad range, since that would let any client spoof its IP and dodge per-IP rate limiting.
- See `../docs/env_matrix.md` for the full deploy-time variable matrix.

## Run

```bash
uvicorn app.main:app --reload
```

On startup, the backend prints which AI mode is active.

You can also confirm the current mode from the API:

```bash
curl http://localhost:8000/tailor/settings/status
```
