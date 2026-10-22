import json
import logging
import os
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

from kitchen_ai import image_to_operations, prompt_to_operations  # noqa: E402  (needs env loaded first)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("decormatrix")

app = FastAPI(
    title="DecorMatrix Kitchen AI",
    description="Turns a design prompt into kitchen plan operations for the app's layout engine",
    version="3.0.0",
)

origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# --- Auth: the caller must be a signed-in DecorMatrix (Supabase) user -------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
AUTH_ENABLED = bool(SUPABASE_URL and SUPABASE_ANON_KEY)
if not AUTH_ENABLED:
    log.warning("SUPABASE_URL / SUPABASE_ANON_KEY not set: /api/kitchen/ai is OPEN (development mode)")

_token_cache: Dict[str, tuple] = {}  # token -> (user_id, expires_at)


def _user_from_token(authorization: Optional[str]) -> str:
    if not AUTH_ENABLED:
        return "dev"
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in to use the AI designer")
    token = authorization[7:].strip()
    cached = _token_cache.get(token)
    if cached and cached[1] > time.time():
        return cached[0]
    req = urllib.request.Request(
        f"{SUPABASE_URL}/auth/v1/user",
        headers={"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as res:
            user = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        log.warning("Supabase token check failed: %s %s", e.code, body)
        # Supabase answers 403 bad_jwt for an expired/invalid user token; anything else
        # (e.g. 401 "Invalid API key", 404 wrong URL) is our SUPABASE_* config.
        if e.code == 403 or "jwt" in body.lower():
            raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
        raise HTTPException(status_code=502, detail="AI server sign-in check is misconfigured")
    except Exception as e:
        log.warning("Supabase token check unreachable: %r", e)
        raise HTTPException(status_code=503, detail="Could not verify your session. Try again shortly.")
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid session")
    _token_cache[token] = (user_id, time.time() + 300)
    return user_id


# --- Rate limit: per user, sliding window -------------------------------------------------------
RATE_LIMIT = int(os.getenv("AI_RATE_LIMIT", "20"))
RATE_WINDOW = int(os.getenv("AI_RATE_WINDOW_SECONDS", "300"))
_calls: Dict[str, deque] = defaultdict(deque)


def _check_rate(key: str) -> None:
    now = time.time()
    q = _calls[key]
    while q and q[0] < now - RATE_WINDOW:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many AI requests. Please wait a few minutes.")
    q.append(now)


# --- API ------------------------------------------------------------------------------------------
class KitchenAiRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=1000)
    plan: Dict[str, Any]


IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
MAX_IMAGE_BASE64 = 8_000_000  # ~6 MB photo


class KitchenImageRequest(BaseModel):
    image: str = Field(..., min_length=100, max_length=MAX_IMAGE_BASE64)
    mimeType: str = "image/jpeg"
    prompt: str = Field("", max_length=1000)
    plan: Dict[str, Any]


class KitchenAiResponse(BaseModel):
    operations: list
    summary: str


def _supabase_diagnostics() -> Dict[str, Any]:
    """Explains why the sign-in check can't reach Supabase. Never echoes the key itself."""
    url = SUPABASE_URL
    key = SUPABASE_ANON_KEY
    diag: Dict[str, Any] = {
        # The project URL is public (it ships in the app bundle); repr() exposes stray quotes/whitespace.
        "url": repr(url),
        "url_has_https": url.startswith("https://"),
        "url_looks_like_supabase": url.endswith(".supabase.co"),
        "key_kind": (
            "missing" if not key
            else "publishable" if key.startswith("sb_publishable_")
            else "secret (wrong key!)" if key.startswith("sb_secret_")
            else "legacy jwt" if key.startswith("eyJ")
            else "unrecognised"
        ),
        "key_has_whitespace_or_quotes": key != key.strip().strip("\"'"),
    }
    req = urllib.request.Request(f"{url}/auth/v1/settings", headers={"apikey": key})
    try:
        with urllib.request.urlopen(req, timeout=8) as res:
            diag["probe"] = f"ok {res.status}"
    except urllib.error.HTTPError as e:
        diag["probe"] = f"http {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
    except Exception as e:
        diag["probe"] = f"unreachable: {e!r}"[:300]
    return diag


@app.get("/health")
def health(check: Optional[str] = None):
    out: Dict[str, Any] = {"status": "online", "service": "DecorMatrix Kitchen AI", "auth": AUTH_ENABLED}
    if check == "supabase":
        out["supabase"] = _supabase_diagnostics()
    return out


@app.post("/api/kitchen/ai", response_model=KitchenAiResponse)
def kitchen_ai(req: KitchenAiRequest, request: Request, authorization: Optional[str] = Header(default=None)):
    user_id = _user_from_token(authorization)
    _check_rate(user_id if AUTH_ENABLED else (request.client.host if request.client else "anon"))

    if len(json.dumps(req.plan)) > 60_000:
        raise HTTPException(status_code=413, detail="Kitchen plan is too large")
    try:
        result = prompt_to_operations(req.prompt.strip(), req.plan)
    except Exception as e:
        log.exception("AI request failed")
        raise HTTPException(status_code=502, detail=f"AI designer is unavailable: {e}")
    log.info("user=%s model=%s ops=%d", user_id, result.get("model"), len(result["operations"]))
    return {"operations": result["operations"], "summary": result["summary"]}


@app.post("/api/kitchen/ai/image", response_model=KitchenAiResponse)
def kitchen_ai_image(req: KitchenImageRequest, request: Request, authorization: Optional[str] = Header(default=None)):
    """Reference photo -> arrangement and finishes for the modules already in the plan."""
    user_id = _user_from_token(authorization)
    _check_rate(user_id if AUTH_ENABLED else (request.client.host if request.client else "anon"))

    mime = req.mimeType.lower()
    if mime not in IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Use a JPEG, PNG or WebP photo")
    if len(json.dumps(req.plan)) > 60_000:
        raise HTTPException(status_code=413, detail="Kitchen plan is too large")
    image = req.image.split(",", 1)[1] if req.image.startswith("data:") else req.image
    try:
        result = image_to_operations(image, mime, req.prompt.strip(), req.plan)
    except Exception as e:
        log.exception("AI image request failed")
        raise HTTPException(status_code=502, detail=f"AI designer is unavailable: {e}")
    log.info("user=%s model=%s image ops=%d", user_id, result.get("model"), len(result["operations"]))
    return {"operations": result["operations"], "summary": result["summary"]}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"[STARTING] DecorMatrix Kitchen AI on http://{host}:{port}")
    uvicorn.run("main:app", host=host, port=port, reload=os.getenv("RELOAD", "1") == "1")
