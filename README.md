# DecorMatrix Kitchen AI

Turns a design prompt (English / Hindi / Hinglish) into operations on the app's kitchen plan.
The model only translates intent; the app's layout engine (`DecorMatrix/src/kitchen/engine.ts`)
applies the operations and enforces every fit, overlap and window/door rule.

```
POST /api/kitchen/ai   { "prompt": "...", "plan": { ...compact plan... } }
  -> { "operations": [ { "op": "auto_design", "brief": {...} }, ... ], "summary": "..." }
GET  /health
```

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env        # set GEMINI_API_KEY
python main.py              # http://localhost:8000
```

With `SUPABASE_URL` / `SUPABASE_ANON_KEY` unset the endpoint is open (development only).

## Deploy (Render, Railway, Cloud Run…)

- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Set `GEMINI_API_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY` (the app's publishable key),
  and `ALLOWED_ORIGINS` to the web app's origin.
- Point the app at it: `EXPO_PUBLIC_KITCHEN_AI_URL=https://<your-backend>` in `DecorMatrix/.env`,
  then rebuild (web export / APK).

Each request is checked against Supabase (`/auth/v1/user`) and limited to `AI_RATE_LIMIT`
calls per user per `AI_RATE_WINDOW_SECONDS`.

## Files

- `main.py` – API, auth, rate limit
- `kitchen_ai.py` – prompt, Gemini call (JSON mode, model fallback), output sanitising
