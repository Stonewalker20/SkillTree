# Environment Matrix

This matrix lists the runtime variables required to deploy SkillBridge safely.

## Backend Runtime

| Variable | Required | Purpose | Example |
| --- | --- | --- | --- |
| `APP_ENV` | yes | Runtime mode. Use `staging` or `production` outside local dev. | `production` |
| `ALLOWED_ORIGINS` | yes | Comma-separated frontend origins allowed by CORS. | `https://skillbridge.app` |
| `MONGO_URI` | yes | MongoDB connection string. Must not use localhost outside development. | `mongodb+srv://...` |
| `MONGO_DB` | yes | Database name for the target environment. | `skillbridge` |
| `PUBLIC_APP_URL` | yes | Public frontend base URL used for links and billing callbacks. | `https://skillbridge.app` |
| `PUBLIC_API_URL` | yes | Public backend base URL. | `https://api.skillbridge.app` |
| `PASSWORD_RESET_TOKEN_TTL_MINUTES` | recommended | Lifetime for password reset tokens. | `60` |
| `SMTP_HOST` | recommended for password reset email delivery | SMTP hostname for outbound transactional email. | `smtp.sendgrid.net` |
| `SMTP_PORT` | recommended | SMTP port. Usually `587` for STARTTLS or `465` for SSL. | `587` |
| `SMTP_USERNAME` | recommended when SMTP auth is required | SMTP username or API user. | `apikey` |
| `SMTP_PASSWORD` | recommended when SMTP auth is required | SMTP password or API key. | `replace-me` |
| `SMTP_FROM_EMAIL` | recommended for password reset email delivery | Sender email address for auth emails. | `no-reply@skillbridge.app` |
| `SMTP_FROM_NAME` | optional | Sender display name for auth emails. | `SkillBridge` |
| `SMTP_REPLY_TO` | optional | Reply-to address for auth emails. | `support@skillbridge.app` |
| `SMTP_USE_STARTTLS` | optional | Whether to upgrade SMTP connections with STARTTLS. | `true` |
| `SMTP_USE_SSL` | optional | Whether to connect via implicit SSL. | `false` |
| `ADMIN_OWNER_EMAILS` | recommended | Comma-separated emails that should receive owner access on registration. | `owner@example.com` |
| `ADMIN_TEAM_EMAILS` | recommended | Comma-separated emails that should receive team access on registration. | `team@example.com` |
| `TRUSTED_PROXY_CIDRS` | recommended when deployed behind a reverse proxy or load balancer | Comma-separated CIDR ranges allowed to set `X-Forwarded-For`/`X-Real-IP`. Used to determine the real client IP for rate limiting and audit logs. Leave empty if the backend is reachable directly. | `10.0.0.0/8,172.16.0.0/12` |

## Billing

| Variable | Required | Purpose | Example |
| --- | --- | --- | --- |
| `STRIPE_SECRET_KEY` | yes for live billing | Stripe API secret key. | `sk_live_...` |
| `STRIPE_WEBHOOK_SECRET` | yes for live billing | Verifies webhook deliveries from Stripe. | `whsec_...` |
| `STRIPE_PRICE_ID_STARTER` | yes for tiered checkout | Stripe price for Starter. | `price_...` |
| `STRIPE_PRICE_ID_PRO` | yes for tiered checkout | Stripe price for Pro. | `price_...` |
| `STRIPE_PRICE_ID_ELITE` | yes for tiered checkout | Stripe price for Elite. | `price_...` |
| `STRIPE_PRICE_ID` | optional fallback | Legacy fallback for Pro if `STRIPE_PRICE_ID_PRO` is omitted. | `price_...` |
| `STRIPE_CURRENCY` | optional | Display currency passed through billing status. | `usd` |
| `STRIPE_SUCCESS_URL` | recommended | Checkout success redirect. | `https://skillbridge.app/app/account?checkout=success` |
| `STRIPE_CANCEL_URL` | recommended | Checkout cancellation redirect. | `https://skillbridge.app/app/account?checkout=cancelled` |
| `STRIPE_BILLING_PORTAL_RETURN_URL` | recommended | Return target from the Stripe billing portal. | `https://skillbridge.app/app/account` |

## Media Storage

| Variable | Required | Purpose | Example |
| --- | --- | --- | --- |
| `MEDIA_STORAGE_MODE` | yes | `local` for local dev only, `s3` for deploys. | `s3` |
| `MEDIA_S3_ENDPOINT_URL` | yes when `MEDIA_STORAGE_MODE=s3` | S3 or R2 endpoint URL. | `https://<account>.r2.cloudflarestorage.com` |
| `MEDIA_S3_BUCKET` | yes when `MEDIA_STORAGE_MODE=s3` | Bucket name for avatar/media assets. | `skillbridge-media` |
| `MEDIA_S3_REGION` | yes when `MEDIA_STORAGE_MODE=s3` | Bucket region. | `auto` |
| `MEDIA_S3_ACCESS_KEY_ID` | yes when `MEDIA_STORAGE_MODE=s3` | Object storage access key. | `replace-me` |
| `MEDIA_S3_SECRET_ACCESS_KEY` | yes when `MEDIA_STORAGE_MODE=s3` | Object storage secret key. | `replace-me` |
| `MEDIA_S3_PUBLIC_BASE_URL` | recommended | Public base URL for served media. | `https://media.skillbridge.app` |
| `MEDIA_S3_KEY_PREFIX` | optional | Prefix used for stored avatar objects. | `avatars` |
| `USER_AVATAR_UPLOAD_DIR` | optional | Local fallback upload directory. | `backend/data/uploads/avatars` |

## Model Selection

| Variable | Required | Purpose | Example |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` | optional | Enables hosted OpenAI inference when configured. | `sk-...` |
| `OPENAI_EMBED_MODEL` | optional | Hosted embedding model. | `text-embedding-3-small` |
| `OPENAI_CHAT_MODEL` | optional | Hosted chat/rewrite model. | `gpt-4o-mini` |
| `LOCAL_EMBEDDING_MODEL` | optional | Local embeddings model. | `sentence-transformers/all-MiniLM-L6-v2` |
| `LOCAL_ZERO_SHOT_MODEL` | optional | Local zero-shot skill filter model. | `MoritzLaurer/deberta-v3-base-zeroshot-v1.1-all-33` |
| `LOCAL_REWRITE_MODEL` | optional | Local rewrite model. | `google/flan-t5-small` |
| `LOCAL_MODEL_DEVICE` | optional | `-1` for CPU, GPU index otherwise. | `-1` |
| `LOCAL_MODEL_PREWARM` | optional | Whether to load local models at startup. | `true` |

## Frontend Runtime

| Variable | Required | Purpose | Example |
| --- | --- | --- | --- |
| `VITE_API_BASE` | yes outside local dev | Public API base URL for the deployed frontend. | `https://api.skillbridge.app` |

## Notes

- `frontend/.env.staging.example` and `frontend/.env.production.example` cover the public frontend runtime.
- `backend/.env.staging.example` and `backend/.env.production.example` cover the backend runtime.
- Password reset emails are sent through SMTP when the SMTP settings above are configured.
- New passwords should be at least 15 characters long. A mix of letters, numbers, and symbols is recommended.
- Set `TRUSTED_PROXY_CIDRS` to the CIDR range(s) of your load balancer or reverse proxy (e.g. your cloud provider's ALB/ingress subnet) when deploying behind one. Only requests whose socket peer address falls inside one of these ranges have their `X-Forwarded-For`/`X-Real-IP` headers trusted; everyone else's forwarded headers are ignored. Leaving it empty is safe but means rate limiting and audit logs will key off the proxy's IP instead of the real client IP for every request. Setting it too broadly (e.g. `0.0.0.0/0`) lets any client spoof its own IP and bypass per-IP throttling, so scope it to the actual proxy/load balancer network only.
