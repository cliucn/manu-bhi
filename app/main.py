import fnmatch
import os
import re
import json
import time
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
import google.auth
import jwt
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from google.auth.transport import requests as ga_requests
from google.oauth2 import id_token as g_id_token
from google.cloud import bigquery

app = FastAPI(
    title="Google SSO Enterprise Portal",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

APP_AUTH = os.getenv("APP_AUTH", "1") == "1"
OAUTH_CLIENT_ID = os.getenv(
    "OAUTH_CLIENT_ID",
    "258087247677-5frpsumdj01fbrp6uhbqnjfhaiihvvt3.apps.googleusercontent.com"
).strip()
SESSION_SECRET = os.getenv("SESSION_SECRET", "").strip()
COOKIE_NAME = os.getenv("COOKIE_NAME", "argolis_app_session").strip()
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "604800"))  # 默认 7 天 (604800 秒)
SESSION_RENEW_RATIO = float(os.getenv("SESSION_RENEW_RATIO", "0.5"))   # 剩余有效期低于 50% (3.5天) 时滑动续期
ALLOWED_DOMAINS = [
    d.strip().lower() for d in
    os.getenv("ALLOWED_DOMAINS", "google.com,*.altostrat.com").split(",") if d.strip()
]
DEFAULT_ALLOWED_USERS = "liuchenggang@google.com,levichen@google.com,yhugo@google.com,xwzeng@google.com"
ALLOWED_USERS = {
    u.strip().lower()
    for u in re.split(r"[,;\s]+", os.getenv("ALLOWED_USERS", DEFAULT_ALLOWED_USERS))
    if u.strip()
}

_GOOGLE_REQUEST = ga_requests.Request()

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "cliu201-477811")
DATASET_ID = os.getenv("BQ_DATASET", "bhi_manu")
DEFAULT_SA_KEY_PATH = os.getenv(
    "TARGET_SA_KEY_PATH",
    "/usr/local/google/home/liuchenggang/.config/gcloud/legacy_credentials/byd-sa@cliu201-477811.iam.gserviceaccount.com/adc.json",
)


def _get_project_sa_credentials():
    """Authenticate to cliu201-477811 using the Cloud Run bound Service Account (byd-sa@cliu201-477811.iam.gserviceaccount.com)."""
    if os.path.exists(DEFAULT_SA_KEY_PATH):
        from google.oauth2 import service_account

        return service_account.Credentials.from_service_account_file(
            DEFAULT_SA_KEY_PATH,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return creds


bq_client = bigquery.Client(project=PROJECT_ID, credentials=_get_project_sa_credentials())


class SessionExchangeRequest(BaseModel):
    credential: str


def _now() -> int:
    return int(time.time())


def is_domain_allowed(email: str) -> bool:
    if not email or "@" not in email:
        return False
    domain = email.rsplit("@", 1)[-1].lower()
    for pattern in ALLOWED_DOMAINS:
        if pattern.startswith("*."):
            suffix = pattern[2:]
            if domain == suffix or domain.endswith("." + suffix):
                return True
        elif fnmatch.fnmatch(domain, pattern):
            return True
    return False


def _user_ok(email: str) -> bool:
    e = (email or "").strip().lower()
    if not e or not is_domain_allowed(e):
        return False
    if ALLOWED_USERS:
        return e in ALLOWED_USERS
    return True


def extract_cookie_token(raw_cookie_header: str, cookie_name: str) -> str:
    """按分号安全提取目标 Cookie，避免 GIS 写入的 g_state={"i_l":0} 搞崩标准库 SimpleCookie。"""
    if not raw_cookie_header:
        return ""
    for chunk in raw_cookie_header.split(";"):
        part = chunk.strip()
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        if k.strip() == cookie_name and v.strip():
            return v.strip()
    return ""


def create_session_jwt(email: str, name: str = "", now_ts: Optional[int] = None) -> Dict[str, Any]:
    if not SESSION_SECRET:
        raise HTTPException(503, "SESSION_SECRET is not configured on the server.")
    iat = now_ts if now_ts is not None else _now()
    exp = iat + SESSION_TTL_SECONDS
    payload = {
        "sub": email,
        "email": email,
        "name": name or email,
        "iat": iat,
        "exp": exp,
        "type": "app_session",
    }
    token = jwt.encode(payload, SESSION_SECRET, algorithm="HS256")
    return {"token": token, "payload": payload}


def verify_session_jwt(token_str: str, now_ts: Optional[int] = None) -> Optional[Dict[str, Any]]:
    if not SESSION_SECRET or not token_str:
        return None
    try:
        claims = jwt.decode(
            token_str,
            SESSION_SECRET,
            algorithms=["HS256"],
            options={"verify_exp": False},
        )
        now_val = now_ts if now_ts is not None else _now()
        if int(claims.get("exp", 0)) <= now_val or claims.get("type") != "app_session":
            return None
        return claims
    except jwt.PyJWTError:
        return None


def set_session_cookie(response: Response, token: str, max_age: int) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=max_age,
        path="/",
        httponly=True,
        secure=True,
        samesite="lax",
    )


def verify_google_id_token(id_token_str: str) -> Dict[str, Any]:
    if not OAUTH_CLIENT_ID:
        raise HTTPException(503, "OAUTH_CLIENT_ID is not configured.")
    try:
        idinfo = g_id_token.verify_oauth2_token(
            id_token_str, _GOOGLE_REQUEST, OAUTH_CLIENT_ID
        )
    except Exception as exc:
        raise HTTPException(401, f"Invalid or expired Google ID token: {exc}") from exc

    email = (idinfo.get("email") or "").strip().lower()
    if not idinfo.get("email_verified") or not _user_ok(email):
        raise HTTPException(403, f"User '{email}' is not in the authorized allowlist.")
    return {
        "email": email,
        "name": idinfo.get("name") or email,
        "sub": idinfo.get("sub") or email,
    }


async def require_session(request: Request, response: Response) -> Dict[str, Any]:
    # 1. 若挂载在 ALB + LbTrafficExtension 网关后，自动信任网关注入头并校验白名单
    gw_email = request.headers.get("x-authenticated-user-email", "").strip().lower()
    if gw_email and _user_ok(gw_email):
        return {
            "email": gw_email,
            "name": request.headers.get("x-authenticated-user-name", gw_email),
            "auth_source": "alb_gateway",
            "iat": None,
            "exp": None,
            "remaining_seconds": None,
            "renewed": False,
        }

    if not APP_AUTH:
        return {
            "email": "liuchenggang@google.com",
            "name": "Auth Disabled",
            "auth_source": "disabled",
            "iat": None,
            "exp": None,
            "remaining_seconds": None,
            "renewed": False,
        }

    # 2. 优先校验长效 Session Cookie 或 Authorization: Bearer <app_session_jwt>
    cookie_token = extract_cookie_token(request.headers.get("cookie", ""), COOKIE_NAME)
    auth_header = request.headers.get("authorization", "")
    bearer_token = (
        auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""
    )

    now_val = _now()
    for source_name, candidate in (("session_cookie", cookie_token), ("session_bearer", bearer_token)):
        if not candidate:
            continue
        claims = verify_session_jwt(candidate, now_ts=now_val)
        if claims:
            email = (claims.get("email") or "").lower()
            if not _user_ok(email):
                raise HTTPException(403, f"User '{email}' is no longer in the authorized allowlist.")
            exp = int(claims["exp"])
            iat = int(claims.get("iat", now_val))
            remaining = exp - now_val
            renewed = False

            # 滑动窗口自动续期：当剩余有效期不足阈值（默认 50%）时，自动重新签发并顺延回完整周期
            if remaining < int(SESSION_TTL_SECONDS * SESSION_RENEW_RATIO):
                minted = create_session_jwt(
                    email=email, name=claims.get("name", email), now_ts=now_val
                )
                set_session_cookie(response, minted["token"], SESSION_TTL_SECONDS)
                response.headers["x-session-renewed"] = "true"
                response.headers["x-session-token"] = minted["token"]
                iat = minted["payload"]["iat"]
                exp = minted["payload"]["exp"]
                remaining = exp - now_val
                renewed = True

            return {
                "email": email,
                "name": claims.get("name", email),
                "auth_source": source_name,
                "iat": iat,
                "exp": exp,
                "remaining_seconds": remaining,
                "renewed": renewed,
            }

    # 3. 兼容降级：若客户端直接传了 1 小时的 Google ID Token，验签后自动升级下发长效 Session Cookie
    if bearer_token:
        google_user = verify_google_id_token(bearer_token)
        minted = create_session_jwt(
            email=google_user["email"], name=google_user["name"], now_ts=now_val
        )
        set_session_cookie(response, minted["token"], SESSION_TTL_SECONDS)
        response.headers["x-session-renewed"] = "true"
        response.headers["x-session-token"] = minted["token"]
        return {
            "email": google_user["email"],
            "name": google_user["name"],
            "auth_source": "google_id_token_upgraded",
            "iat": minted["payload"]["iat"],
            "exp": minted["payload"]["exp"],
            "remaining_seconds": SESSION_TTL_SECONDS,
            "renewed": True,
        }

    raise HTTPException(401, "Missing or expired session. Please sign in with Google.")


async def require_user(session: Dict[str, Any] = Depends(require_session)) -> str:
    return session["email"]


ADMIN_EMAIL = "liuchenggang@google.com"


def _is_admin(email: str) -> bool:
    return (email or "").strip().lower() == ADMIN_EMAIL


async def require_admin(user: str = Depends(require_user)) -> str:
    if not _is_admin(user):
        raise HTTPException(404, "Not Found")
    return user


def _extract_client_ip(request: Optional[Request]) -> str:
    if not request:
        return ""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return ""


def _log_audit_event(
    user_email: str,
    event_type: str,
    path_or_action: str,
    detail: str = "",
    request: Optional[Request] = None,
) -> None:
    """Asynchronously record user access/activity into BigQuery without blocking the HTTP response."""
    email_clean = (user_email or "").strip().lower()
    if not email_clean:
        return
    ip = _extract_client_ip(request)
    ua = (request.headers.get("user-agent", "") if request else "")[:300]

    def _insert():
        try:
            import datetime
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            cst_tz = datetime.timezone(datetime.timedelta(hours=8))
            now_cst = now_utc.astimezone(cst_tz)
            row = {
                "event_time": now_utc.strftime("%Y-%m-%d %H:%M:%S.%f UTC"),
                "event_date_cst": now_cst.strftime("%Y-%m-%d"),
                "user_email": email_clean,
                "event_type": event_type[:64],
                "path_or_action": path_or_action[:160],
                "detail": (detail or "")[:400],
                "client_ip": ip[:80],
                "user_agent": ua,
            }
            table_id = f"{PROJECT_ID}.{DATASET_ID}.portal_access_audit_logs"
            bq_client.insert_rows_json(table_id, [row])
        except Exception:
            pass

    _BQ_EXECUTOR.submit(_insert)


@app.post("/api/auth/session")
async def exchange_session(body: SessionExchangeRequest, request: Request, response: Response):
    """将 1 小时有效期的 Google ID Token 换签为 7 天（可配 30 天）有效的无状态应用 Session。"""
    google_user = verify_google_id_token(body.credential)
    minted = create_session_jwt(email=google_user["email"], name=google_user["name"])
    set_session_cookie(response, minted["token"], SESSION_TTL_SECONDS)
    _log_audit_event(
        google_user["email"],
        "SSO_LOGIN",
        "/api/auth/session",
        "Google SSO 身份验证并签发 7 天长效会话",
        request,
    )
    return {
        "ok": True,
        "email": google_user["email"],
        "name": google_user["name"],
        "is_admin": _is_admin(google_user["email"]),
        "session_token": minted["token"],
        "expires_in": SESSION_TTL_SECONDS,
        "exp": minted["payload"]["exp"],
    }


@app.post("/api/auth/logout")
@app.get("/api/auth/logout")
async def logout(request: Request):
    resp = RedirectResponse(url="/", status_code=302) if request.method == "GET" else JSONResponse({"ok": True})
    resp.delete_cookie(key=COOKIE_NAME, path="/", httponly=True, secure=True, samesite="lax")
    return resp


@app.get("/api/whoami")
async def whoami(session: Dict[str, Any] = Depends(require_session)):
    return {
        "ok": True,
        "user": session["email"],
        "name": session["name"],
        "is_admin": _is_admin(session["email"]),
        "auth_source": session["auth_source"],
        "iat": session["iat"],
        "exp": session["exp"],
        "remaining_seconds": session["remaining_seconds"],
        "sliding_renewed": session["renewed"],
        "configured_ttl_seconds": SESSION_TTL_SECONDS,
    }


from concurrent.futures import ThreadPoolExecutor

_BQ_EXECUTOR = ThreadPoolExecutor(max_workers=8)
_DATA_CACHE: Dict[str, Any] = {}
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "3600"))
CACHE_SCHEMA_VERSION = "v2.1"


def _get_cached(key: str, compute_fn, force_refresh: bool = False):
    now_ts = time.time()
    entry = _DATA_CACHE.get(key)
    if not force_refresh and entry and (now_ts - entry["ts"] < CACHE_TTL_SECONDS):
        return entry["val"]
    val = compute_fn()
    _DATA_CACHE[key] = {"ts": now_ts, "val": val}
    return val


@app.get("/api/cache/status")
async def api_cache_status(user: str = Depends(require_user)):
    """Lightweight metadata check (<5ms) for frontend Stale-While-Revalidate (SWR)."""
    now_ts = time.time()
    qa_entry = _DATA_CACHE.get("quota_attainment")
    meta = {}
    if qa_entry and isinstance(qa_entry.get("val"), dict):
        meta = qa_entry["val"].get("metadata", {})
    return {
        "schema_version": CACHE_SCHEMA_VERSION,
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
        "cached_keys": list(_DATA_CACHE.keys()),
        "quota_cache_age_seconds": round(now_ts - qa_entry["ts"], 1) if qa_entry else None,
        "metadata": meta,
    }


@app.post("/api/cache/clear")
async def api_cache_clear(request: Request, user: str = Depends(require_user)):
    """Clear all backend in-memory caches so subsequent requests pull fresh BigQuery data."""
    cleared_count = len(_DATA_CACHE)
    _DATA_CACHE.clear()
    _log_audit_event(
        user,
        "CACHE_REFRESH",
        "/api/cache/clear",
        f"手动清空缓存并强制重新拉取最新数据 (清理 {cleared_count} 个缓存项)",
        request,
    )
    return {"ok": True, "cleared_keys": cleared_count, "user": user}


class AuditTrackRequest(BaseModel):
    event_type: str = "PAGE_VIEW"
    path_or_action: str = "/"
    detail: str = ""


@app.post("/api/audit/track")
async def api_audit_track(body: AuditTrackRequest, request: Request, user: str = Depends(require_user)):
    """Lightweight non-blocking telemetry endpoint for recording authenticated user page views & tab switches."""
    _log_audit_event(user, body.event_type, body.path_or_action, body.detail, request)
    return {"ok": True}


@app.get("/authconfig")
async def authconfig():
    return {
        "app_auth": APP_AUTH,
        "client_id": OAUTH_CLIENT_ID,
        "session_ttl_seconds": SESSION_TTL_SECONDS,
        "cookie_name": COOKIE_NAME,
    }


@app.get("/health")
@app.get("/healthz")
async def health():
    return {"ok": True, "status": "ok"}

@app.get("/api/overview")
async def api_overview(refresh: int = 0, user: str = Depends(require_user)):
    def _compute():
        query = f"""
        SELECT
          ROUND(SUM(total_gcp_gross_rev), 2) AS total_gcp_gross,
          ROUND(SUM(total_gcp_rvp_rev), 2) AS total_gcp_rvp,
          ROUND(SUM(total_cloud_ai_gross_rev), 2) AS total_cloud_ai_gross,
          ROUND(SUM(total_cloud_ai_rvp_rev), 2) AS total_cloud_ai_rvp,
          ROUND(SUM(total_da_gross_rev), 2) AS total_da_gross,
          ROUND(SUM(total_da_rvp_rev), 2) AS total_da_rvp,
          ROUND(SUM(total_db_gross_rev), 2) AS total_db_gross,
          ROUND(SUM(total_db_rvp_rev), 2) AS total_db_rvp,
          ROUND(SUM(total_ge_gross_rev), 2) AS total_ge_gross,
          ROUND(SUM(total_ge_rvp_rev), 2) AS total_ge_rvp,

          -- Latest DRR
          ROUND(SUM(latest_gcp_gross_drr), 2) AS latest_gcp_gross_drr,
          ROUND(SUM(latest_gcp_rvp_drr), 2) AS latest_gcp_rvp_drr,
          ROUND(SUM(latest_cloud_ai_gross_drr), 2) AS latest_cloud_ai_gross_drr,
          ROUND(SUM(latest_cloud_ai_rvp_drr), 2) AS latest_cloud_ai_rvp_drr,
          ROUND(SUM(latest_da_gross_drr), 2) AS latest_da_gross_drr,
          ROUND(SUM(latest_da_rvp_drr), 2) AS latest_da_rvp_drr,
          ROUND(SUM(latest_db_gross_drr), 2) AS latest_db_gross_drr,
          ROUND(SUM(latest_db_rvp_drr), 2) AS latest_db_rvp_drr,
          ROUND(SUM(latest_ge_gross_drr), 2) AS latest_ge_gross_drr,
          ROUND(SUM(latest_ge_rvp_drr), 2) AS latest_ge_rvp_drr,

          -- Current Month MTD MRR
          ROUND(SUM(current_month_gcp_gross_mrr), 2) AS current_month_gcp_gross_mrr,
          ROUND(SUM(current_month_gcp_rvp_mrr), 2) AS current_month_gcp_rvp_mrr,
          ROUND(SUM(current_month_cloud_ai_gross_mrr), 2) AS current_month_cloud_ai_gross_mrr,
          ROUND(SUM(current_month_cloud_ai_rvp_mrr), 2) AS current_month_cloud_ai_rvp_mrr,
          ROUND(SUM(current_month_da_gross_mrr), 2) AS current_month_da_gross_mrr,
          ROUND(SUM(current_month_da_rvp_mrr), 2) AS current_month_da_rvp_mrr,
          ROUND(SUM(current_month_db_gross_mrr), 2) AS current_month_db_gross_mrr,
          ROUND(SUM(current_month_db_rvp_mrr), 2) AS current_month_db_rvp_mrr,
          ROUND(SUM(current_month_ge_gross_mrr), 2) AS current_month_ge_gross_mrr,
          ROUND(SUM(current_month_ge_rvp_mrr), 2) AS current_month_ge_rvp_mrr,

          -- Prior Month Full MRR
          ROUND(SUM(prior_month_gcp_gross_mrr), 2) AS prior_month_gcp_gross_mrr,
          ROUND(SUM(prior_month_gcp_rvp_mrr), 2) AS prior_month_gcp_rvp_mrr,
          ROUND(SUM(prior_month_cloud_ai_gross_mrr), 2) AS prior_month_cloud_ai_gross_mrr,
          ROUND(SUM(prior_month_cloud_ai_rvp_mrr), 2) AS prior_month_cloud_ai_rvp_mrr,
          ROUND(SUM(prior_month_da_gross_mrr), 2) AS prior_month_da_gross_mrr,
          ROUND(SUM(prior_month_da_rvp_mrr), 2) AS prior_month_da_rvp_mrr,
          ROUND(SUM(prior_month_db_gross_mrr), 2) AS prior_month_db_gross_mrr,
          ROUND(SUM(prior_month_db_rvp_mrr), 2) AS prior_month_db_rvp_mrr,
          ROUND(SUM(prior_month_ge_gross_mrr), 2) AS prior_month_ge_gross_mrr,
          ROUND(SUM(prior_month_ge_rvp_mrr), 2) AS prior_month_ge_rvp_mrr,

          COUNT(*) AS total_customers
        FROM `{PROJECT_ID}.{DATASET_ID}.customer_revenue_scorecard_2026`
        """
        rows = list(bq_client.query(query).result())
        if not rows:
            return {}
        r = dict(rows[0])
        for k, v in r.items():
            if hasattr(v, '__float__'):
                r[k] = float(v)
        return r

    r = _get_cached("overview", _compute, force_refresh=(refresh == 1))
    return {"user": user, "is_admin": _is_admin(user), "data": r}

@app.get("/api/scorecard")
async def api_scorecard(refresh: int = 0, user: str = Depends(require_user)):
    def _compute():
        query_acc = f"""
        SELECT *
        FROM `{PROJECT_ID}.{DATASET_ID}.customer_revenue_scorecard_2026`
        ORDER BY total_gcp_rvp_rev DESC
        """
        query_nal = f"""
        SELECT *
        FROM `{PROJECT_ID}.{DATASET_ID}.nal_revenue_scorecard_2026`
        ORDER BY total_gcp_rvp_rev DESC
        """
        f_acc = _BQ_EXECUTOR.submit(lambda: [dict(row) for row in bq_client.query(query_acc).result()])
        f_nal = _BQ_EXECUTOR.submit(lambda: [dict(row) for row in bq_client.query(query_nal).result()])
        rows = f_acc.result()
        nal_rows = f_nal.result()
        for r in rows:
            for k, v in r.items():
                if hasattr(v, '__float__'):
                    r[k] = float(v)
        for r in nal_rows:
            for k, v in r.items():
                if hasattr(v, '__float__'):
                    r[k] = float(v)
        return {"rows": rows, "nal_rows": nal_rows}

    return _get_cached("scorecard", _compute, force_refresh=(refresh == 1))

@app.get("/api/monthly")
async def api_monthly(refresh: int = 0, user: str = Depends(require_user)):
    def _compute():
        query = f"""
        SELECT
          year_month,
          MAX(days_in_month) AS days_in_month,
          -- GCP
          ROUND(SUM(gcp_gross_mrr), 2) AS gcp_gross_mrr,
          ROUND(SUM(gcp_rvp_mrr), 2) AS gcp_rvp_mrr,
          ROUND(SUM(gcp_gross_drr_avg), 2) AS gcp_gross_drr_avg,
          ROUND(SUM(gcp_rvp_drr_avg), 2) AS gcp_rvp_drr_avg,
          -- Cloud AI
          ROUND(SUM(cloud_ai_gross_mrr), 2) AS cloud_ai_gross_mrr,
          ROUND(SUM(cloud_ai_rvp_mrr), 2) AS cloud_ai_rvp_mrr,
          -- DA
          ROUND(SUM(da_gross_mrr), 2) AS da_gross_mrr,
          ROUND(SUM(da_rvp_mrr), 2) AS da_rvp_mrr,
          -- DB
          ROUND(SUM(db_gross_mrr), 2) AS db_gross_mrr,
          ROUND(SUM(db_rvp_mrr), 2) AS db_rvp_mrr,
          -- GE
          ROUND(SUM(ge_gross_mrr), 2) AS ge_gross_mrr,
          ROUND(SUM(ge_rvp_mrr), 2) AS ge_rvp_mrr
        FROM `{PROJECT_ID}.{DATASET_ID}.customer_monthly_revenue`
        GROUP BY year_month
        ORDER BY year_month ASC
        """
        rows = [dict(row) for row in bq_client.query(query).result()]
        for r in rows:
            for k, v in r.items():
                if hasattr(v, '__float__'):
                    r[k] = float(v)
        return {"months": rows}

    return _get_cached("monthly", _compute, force_refresh=(refresh == 1))

@app.get("/api/ge-stats")
async def api_ge_stats(refresh: int = 0, user: str = Depends(require_user)):
    def _compute():
        query_items = f"""
        SELECT
          reporting_id,
          account_name,
          nal_name,
          product_l3,
          sku_description,
          order_type,
          booking_type,
          deal_lines,
          orders_count,
          total_seats,
          CAST(first_booking_date AS STRING) AS first_booking_date,
          CAST(latest_booking_date AS STRING) AS latest_booking_date,
          signed_tcv,
          signed_acv,
          comp_new_acv,
          comp_expansion_acv,
          comp_renewal_acv,
          net_iacv,
          total_comp_acv
        FROM `{PROJECT_ID}.{DATASET_ID}.customer_ge_bookings_2026`
        ORDER BY signed_acv DESC
        """
        query_nal = f"""
        SELECT
          nal_name,
          customers_count,
          deal_lines,
          orders_count,
          total_seats,
          signed_tcv,
          signed_acv,
          comp_new_acv,
          comp_expansion_acv,
          comp_renewal_acv,
          raw_net_iacv,
          net_iacv,
          total_comp_acv,
          CAST(latest_booking_date AS STRING) AS latest_booking_date
        FROM `{PROJECT_ID}.{DATASET_ID}.nal_ge_bookings_2026`
        ORDER BY signed_acv DESC
        """
        query_monthly = f"""
        SELECT
          year_month,
          deal_lines,
          customers_count,
          monthly_seats,
          signed_tcv,
          signed_acv,
          comp_new_acv,
          comp_expansion_acv,
          comp_renewal_acv,
          net_iacv
        FROM `{PROJECT_ID}.{DATASET_ID}.ge_monthly_bookings_2026`
        ORDER BY year_month ASC
        """
        f_items = _BQ_EXECUTOR.submit(lambda: [dict(row) for row in bq_client.query(query_items).result()])
        f_nal = _BQ_EXECUTOR.submit(lambda: [dict(row) for row in bq_client.query(query_nal).result()])
        f_monthly = _BQ_EXECUTOR.submit(lambda: [dict(row) for row in bq_client.query(query_monthly).result()])
        rows = f_items.result()
        nal_rows = f_nal.result()
        monthly_rows = f_monthly.result()
        for r in rows:
            for k, v in r.items():
                if hasattr(v, '__float__'):
                    r[k] = float(v)
        for r in nal_rows:
            for k, v in r.items():
                if hasattr(v, '__float__'):
                    r[k] = float(v)
        for r in monthly_rows:
            for k, v in r.items():
                if hasattr(v, '__float__'):
                    r[k] = float(v)
        return {"ge_items": rows, "ge_nal_items": nal_rows, "ge_monthly": monthly_rows}

    return _get_cached("ge_stats", _compute, force_refresh=(refresh == 1))

@app.get("/api/quota-attainment")
async def api_quota_attainment(refresh: int = 0, user: str = Depends(require_user)):
    def _compute():
        query_nal_buckets = f"""
        SELECT
          nal_id,
          nal_name,
          gcp_py_baseline,
          gcp_total_quota,
          gcp_irev_quota,
          gcp_total_actuals,
          gcp_irev_actuals,
          gcp_irev_attainment_pct,
          gcp_total_attainment_pct,
          dadbai_py_baseline,
          dadbai_total_quota,
          dadbai_irev_quota,
          dadbai_total_actuals,
          dadbai_irev_actuals,
          dadbai_irev_attainment_pct,
          dadbai_total_attainment_pct,
          ge_net_acv_quota,
          ge_net_acv_actuals,
          ge_pre_watermark_net_iacv,
          ge_signed_bookings_acv,
          ge_attainment_pct
        FROM `{PROJECT_ID}.{DATASET_ID}.nal_three_buckets_quota_2026`
        ORDER BY gcp_irev_quota DESC
        """
        query_nq = f"""
        SELECT
          quarter,
          product,
          total_rev_quota,
          prior_year_baseline,
          incremental_rev_quota,
          total_rev_actuals,
          incremental_rev_actuals,
          bookings_quota,
          bookings_actuals
        FROM `{PROJECT_ID}.{DATASET_ID}.territory_quarterly_quota_2026`
        ORDER BY product ASC, quarter ASC
        """
        query_meta = f"""
        SELECT
          (SELECT CAST(MAX(usage_date) AS STRING) FROM `{PROJECT_ID}.{DATASET_ID}.customer_daily_runrate`) AS latest_billing_date,
          (SELECT CAST(DATE_ADD(MAX(usage_date), INTERVAL 2 DAY) AS STRING) FROM `{PROJECT_ID}.{DATASET_ID}.customer_daily_runrate`) AS rainmaker_as_of_date,
          (SELECT DATE_DIFF(MAX(usage_date), DATE '2026-01-01', DAY) + 1 FROM `{PROJECT_ID}.{DATASET_ID}.customer_daily_runrate`) AS elapsed_days,
          (SELECT CAST(MAX(latest_booking_date) AS STRING) FROM `{PROJECT_ID}.{DATASET_ID}.customer_ge_bookings_2026`) AS latest_ge_booking_date
        """
        f_nb = _BQ_EXECUTOR.submit(lambda: [dict(row) for row in bq_client.query(query_nal_buckets).result()])
        f_nq = _BQ_EXECUTOR.submit(lambda: [dict(row) for row in bq_client.query(query_nq).result()])
        f_meta = _BQ_EXECUTOR.submit(lambda: list(bq_client.query(query_meta).result()))

        nal_bucket_rows = f_nb.result()
        for r in nal_bucket_rows:
            for k, v in r.items():
                if hasattr(v, '__float__'):
                    r[k] = float(v)

        nq_rows = f_nq.result()
        for r in nq_rows:
            for k, v in r.items():
                if hasattr(v, '__float__'):
                    r[k] = float(v)

        meta_rows = f_meta.result()
        meta = dict(meta_rows[0]) if meta_rows else {}
        try:
            tbl_ref = bq_client.get_table(f"{PROJECT_ID}.{DATASET_ID}.nal_three_buckets_quota_2026")
            if tbl_ref.modified:
                import datetime
                cst_tz = datetime.timezone(datetime.timedelta(hours=8))
                meta["last_updated_cst"] = tbl_ref.modified.astimezone(cst_tz).strftime("%Y-%m-%d %H:%M (北京时间)")
                meta["last_updated_date"] = tbl_ref.modified.astimezone(cst_tz).strftime("%Y-%m-%d")
        except Exception:
            pass

        return {
            "nal_buckets": nal_bucket_rows,
            "quarterly_quotas": nq_rows,
            "metadata": meta,
        }

    return _get_cached("quota_attainment", _compute, force_refresh=(refresh == 1))

@app.get("/api/customer-trend")
async def api_customer_trend(reporting_id: str, refresh: int = 0, user: str = Depends(require_user)):
    def _compute():
        query = f"""
        SELECT
          usage_date,
          gcp_gross_drr, gcp_rvp_drr,
          cloud_ai_gross_drr, cloud_ai_rvp_drr,
          da_gross_drr, da_rvp_drr,
          db_gross_drr, db_rvp_drr,
          ge_gross_drr, ge_rvp_drr
        FROM `{PROJECT_ID}.{DATASET_ID}.customer_daily_runrate`
        WHERE reporting_id = @rep_id
        ORDER BY usage_date ASC
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("rep_id", "STRING", reporting_id)
            ]
        )
        rows = [dict(row) for row in bq_client.query(query, job_config=job_config).result()]
        for r in rows:
            r['usage_date'] = str(r['usage_date'])
            for k, v in r.items():
                if hasattr(v, '__float__'):
                    r[k] = float(v)
        return {"trend": rows}

    return _get_cached(f"cust_trend:{reporting_id}", _compute, force_refresh=(refresh == 1))


@app.get("/api/nal-trend")
async def api_nal_trend(nal_name: str, refresh: int = 0, user: str = Depends(require_user)):
    def _compute():
        if nal_name == "ALL":
            query = f"""
            SELECT
              usage_date,
              ROUND(SUM(gcp_gross_drr), 2) AS gcp_gross_drr,
              ROUND(SUM(gcp_rvp_drr), 2) AS gcp_rvp_drr,
              ROUND(SUM(cloud_ai_gross_drr), 2) AS cloud_ai_gross_drr,
              ROUND(SUM(cloud_ai_rvp_drr), 2) AS cloud_ai_rvp_drr,
              ROUND(SUM(da_gross_drr), 2) AS da_gross_drr,
              ROUND(SUM(da_rvp_drr), 2) AS da_rvp_drr,
              ROUND(SUM(db_gross_drr), 2) AS db_gross_drr,
              ROUND(SUM(db_rvp_drr), 2) AS db_rvp_drr,
              ROUND(SUM(ge_gross_drr), 2) AS ge_gross_drr,
              ROUND(SUM(ge_rvp_drr), 2) AS ge_rvp_drr
            FROM `{PROJECT_ID}.{DATASET_ID}.customer_daily_runrate`
            GROUP BY usage_date
            ORDER BY usage_date ASC
            """
            job_config = bigquery.QueryJobConfig()
        else:
            query = f"""
            SELECT
              usage_date,
              ROUND(SUM(gcp_gross_drr), 2) AS gcp_gross_drr,
              ROUND(SUM(gcp_rvp_drr), 2) AS gcp_rvp_drr,
              ROUND(SUM(cloud_ai_gross_drr), 2) AS cloud_ai_gross_drr,
              ROUND(SUM(cloud_ai_rvp_drr), 2) AS cloud_ai_rvp_drr,
              ROUND(SUM(da_gross_drr), 2) AS da_gross_drr,
              ROUND(SUM(da_rvp_drr), 2) AS da_rvp_drr,
              ROUND(SUM(db_gross_drr), 2) AS db_gross_drr,
              ROUND(SUM(db_rvp_drr), 2) AS db_rvp_drr,
              ROUND(SUM(ge_gross_drr), 2) AS ge_gross_drr,
              ROUND(SUM(ge_rvp_drr), 2) AS ge_rvp_drr
            FROM `{PROJECT_ID}.{DATASET_ID}.customer_daily_runrate`
            WHERE nal_name = @nal_name
            GROUP BY usage_date
            ORDER BY usage_date ASC
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("nal_name", "STRING", nal_name)
                ]
            )
        rows = [dict(row) for row in bq_client.query(query, job_config=job_config).result()]
        for r in rows:
            r['usage_date'] = str(r['usage_date'])
            for k, v in r.items():
                if hasattr(v, '__float__'):
                    r[k] = float(v)
        return {"trend": rows}

    return _get_cached(f"nal_trend:{nal_name}", _compute, force_refresh=(refresh == 1))


@app.get("/api/projects/top")
async def api_projects_top(limit: int = 300, refresh: int = 0, user: str = Depends(require_user)):
    """Return top GCP Projects (from project_revenue_scorecard_2026) and territory project summary stats."""
    limit = max(20, min(limit, 800))

    def _compute():
        query_top = f"""
        SELECT
          project_id,
          project_name,
          project_number,
          billing_account_id,
          reporting_id,
          account_name,
          nal_name,
          active_days,
          active_months,
          ROUND(total_gcp_gross_rev, 2) AS total_gcp_gross_rev,
          ROUND(total_gcp_rvp_rev, 2) AS total_gcp_rvp_rev,
          ROUND(total_cloud_ai_gross_rev, 2) AS total_cloud_ai_gross_rev,
          ROUND(total_cloud_ai_rvp_rev, 2) AS total_cloud_ai_rvp_rev,
          ROUND(total_da_gross_rev, 2) AS total_da_gross_rev,
          ROUND(total_da_rvp_rev, 2) AS total_da_rvp_rev,
          ROUND(total_db_gross_rev, 2) AS total_db_gross_rev,
          ROUND(total_db_rvp_rev, 2) AS total_db_rvp_rev,
          ROUND(total_dadbai_rvp_rev, 2) AS total_dadbai_rvp_rev,
          ROUND(current_month_gcp_rvp_mrr, 2) AS current_month_gcp_rvp_mrr,
          ROUND(current_month_cloud_ai_rvp_mrr, 2) AS current_month_cloud_ai_rvp_mrr,
          ROUND(prior_month_gcp_rvp_mrr, 2) AS prior_month_gcp_rvp_mrr,
          ROUND(prior_month_cloud_ai_rvp_mrr, 2) AS prior_month_cloud_ai_rvp_mrr,
          ROUND(latest_gcp_rvp_drr, 2) AS latest_gcp_rvp_drr,
          ROUND(latest_cloud_ai_rvp_drr, 2) AS latest_cloud_ai_rvp_drr,
          ROUND(latest_7d_avg_gcp_rvp_drr, 2) AS latest_7d_avg_gcp_rvp_drr,
          ROUND(cloud_ai_rvp_penetration_pct, 2) AS cloud_ai_rvp_penetration_pct,
          ROUND(drr_mom_growth_pct, 2) AS drr_mom_growth_pct,
          has_daily_drr_curve
        FROM `{PROJECT_ID}.{DATASET_ID}.project_revenue_scorecard_2026`
        WHERE project_id NOT LIKE 'UNASSIGNED_%'
        ORDER BY total_gcp_rvp_rev DESC
        LIMIT {limit}
        """
        query_summary = f"""
        SELECT
          COUNT(DISTINCT project_id) AS total_projects_count,
          COUNTIF(project_id NOT LIKE 'UNASSIGNED_%') AS named_projects_count,
          COUNTIF(has_daily_drr_curve IS TRUE) AS daily_curve_projects_count,
          COUNTIF(total_cloud_ai_rvp_rev > 0 AND project_id NOT LIKE 'UNASSIGNED_%') AS ai_active_projects_count
        FROM `{PROJECT_ID}.{DATASET_ID}.project_revenue_scorecard_2026`
        """
        f_top = _BQ_EXECUTOR.submit(lambda: [dict(row) for row in bq_client.query(query_top).result()])
        f_sum = _BQ_EXECUTOR.submit(lambda: list(bq_client.query(query_summary).result()))

        top_rows = f_top.result()
        for r in top_rows:
            for k, v in r.items():
                if hasattr(v, '__float__') and not isinstance(v, (bool, int)):
                    r[k] = float(v)

        sum_rows = f_sum.result()
        summary = dict(sum_rows[0]) if sum_rows else {}
        return {
            "summary": summary,
            "projects": top_rows,
        }

    return _get_cached(f"projects_top:{limit}", _compute, force_refresh=(refresh == 1))


@app.get("/api/project-trend")
async def api_project_trend(project_id: str, request: Request, refresh: int = 0, user: str = Depends(require_user)):
    """Return Project scorecard metadata, 2026 Monthly MRR series, and 2026 Daily DRR curve for a given project_id."""
    pid = (project_id or "").strip()
    if not pid:
        raise HTTPException(400, "project_id cannot be empty")
    _log_audit_event(user, "DRILLDOWN", "/api/project-trend", f"查询 Project MRR/DRR 曲线: {pid}", request)

    def _compute():
        # 1. Look up scorecard row(s) matching project_id or project_number (exact first, then prefix/substring fallback)
        query_meta = f"""
        SELECT
          project_id,
          project_name,
          project_number,
          billing_account_id,
          reporting_id,
          account_name,
          nal_name,
          active_days,
          active_months,
          ROUND(SUM(total_gcp_gross_rev), 2) AS total_gcp_gross_rev,
          ROUND(SUM(total_gcp_rvp_rev), 2) AS total_gcp_rvp_rev,
          ROUND(SUM(total_cloud_ai_gross_rev), 2) AS total_cloud_ai_gross_rev,
          ROUND(SUM(total_cloud_ai_rvp_rev), 2) AS total_cloud_ai_rvp_rev,
          ROUND(SUM(total_da_gross_rev), 2) AS total_da_gross_rev,
          ROUND(SUM(total_da_rvp_rev), 2) AS total_da_rvp_rev,
          ROUND(SUM(total_db_gross_rev), 2) AS total_db_gross_rev,
          ROUND(SUM(total_db_rvp_rev), 2) AS total_db_rvp_rev,
          ROUND(SUM(total_dadbai_rvp_rev), 2) AS total_dadbai_rvp_rev,
          ROUND(SUM(current_month_gcp_rvp_mrr), 2) AS current_month_gcp_rvp_mrr,
          ROUND(SUM(current_month_cloud_ai_rvp_mrr), 2) AS current_month_cloud_ai_rvp_mrr,
          ROUND(SUM(prior_month_gcp_rvp_mrr), 2) AS prior_month_gcp_rvp_mrr,
          ROUND(SUM(prior_month_cloud_ai_rvp_mrr), 2) AS prior_month_cloud_ai_rvp_mrr,
          ROUND(SUM(latest_gcp_rvp_drr), 2) AS latest_gcp_rvp_drr,
          ROUND(SUM(latest_cloud_ai_rvp_drr), 2) AS latest_cloud_ai_rvp_drr,
          ROUND(SUM(latest_7d_avg_gcp_rvp_drr), 2) AS latest_7d_avg_gcp_rvp_drr,
          ROUND(AVG(cloud_ai_rvp_penetration_pct), 2) AS cloud_ai_rvp_penetration_pct,
          ROUND(AVG(drr_mom_growth_pct), 2) AS drr_mom_growth_pct,
          LOGICAL_OR(has_daily_drr_curve) AS has_daily_drr_curve
        FROM `{PROJECT_ID}.{DATASET_ID}.project_revenue_scorecard_2026`
        WHERE LOWER(project_id) = LOWER(@pid)
           OR project_number = @pid
        GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9
        ORDER BY total_gcp_rvp_rev DESC
        LIMIT 1
        """
        jc = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("pid", "STRING", pid)]
        )
        meta_rows = [dict(row) for row in bq_client.query(query_meta, job_config=jc).result()]
        if not meta_rows:
            # Fuzzy fallback by substring
            query_fuzzy = f"""
            SELECT
              project_id,
              project_name,
              project_number,
              billing_account_id,
              reporting_id,
              account_name,
              nal_name,
              active_days,
              active_months,
              ROUND(total_gcp_gross_rev, 2) AS total_gcp_gross_rev,
              ROUND(total_gcp_rvp_rev, 2) AS total_gcp_rvp_rev,
              ROUND(total_cloud_ai_gross_rev, 2) AS total_cloud_ai_gross_rev,
              ROUND(total_cloud_ai_rvp_rev, 2) AS total_cloud_ai_rvp_rev,
              ROUND(total_da_gross_rev, 2) AS total_da_gross_rev,
              ROUND(total_da_rvp_rev, 2) AS total_da_rvp_rev,
              ROUND(total_db_gross_rev, 2) AS total_db_gross_rev,
              ROUND(total_db_rvp_rev, 2) AS total_db_rvp_rev,
              ROUND(total_dadbai_rvp_rev, 2) AS total_dadbai_rvp_rev,
              ROUND(current_month_gcp_rvp_mrr, 2) AS current_month_gcp_rvp_mrr,
              ROUND(current_month_cloud_ai_rvp_mrr, 2) AS current_month_cloud_ai_rvp_mrr,
              ROUND(prior_month_gcp_rvp_mrr, 2) AS prior_month_gcp_rvp_mrr,
              ROUND(prior_month_cloud_ai_rvp_mrr, 2) AS prior_month_cloud_ai_rvp_mrr,
              ROUND(latest_gcp_rvp_drr, 2) AS latest_gcp_rvp_drr,
              ROUND(latest_cloud_ai_rvp_drr, 2) AS latest_cloud_ai_rvp_drr,
              ROUND(latest_7d_avg_gcp_rvp_drr, 2) AS latest_7d_avg_gcp_rvp_drr,
              ROUND(cloud_ai_rvp_penetration_pct, 2) AS cloud_ai_rvp_penetration_pct,
              ROUND(drr_mom_growth_pct, 2) AS drr_mom_growth_pct,
              has_daily_drr_curve
            FROM `{PROJECT_ID}.{DATASET_ID}.project_revenue_scorecard_2026`
            WHERE LOWER(project_id) LIKE CONCAT('%', LOWER(@pid), '%')
               OR LOWER(project_name) LIKE CONCAT('%', LOWER(@pid), '%')
            ORDER BY total_gcp_rvp_rev DESC
            LIMIT 1
            """
            meta_rows = [dict(row) for row in bq_client.query(query_fuzzy, job_config=jc).result()]

        if not meta_rows:
            return {"found": False, "project_id": pid, "monthly_mrr": [], "daily_drr": []}

        project_meta = meta_rows[0]
        resolved_pid = project_meta["project_id"]
        for k, v in project_meta.items():
            if hasattr(v, '__float__') and not isinstance(v, (bool, int)):
                project_meta[k] = float(v)

        jc_resolved = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("rpid", "STRING", resolved_pid)]
        )

        query_monthly = f"""
        SELECT
          year_month,
          SUM(active_days_in_month) AS active_days_in_month,
          ROUND(SUM(gcp_gross_mrr), 2) AS gcp_gross_mrr,
          ROUND(SUM(gcp_rvp_mrr), 2) AS gcp_rvp_mrr,
          ROUND(SUM(cloud_ai_gross_mrr), 2) AS cloud_ai_gross_mrr,
          ROUND(SUM(cloud_ai_rvp_mrr), 2) AS cloud_ai_rvp_mrr,
          ROUND(SUM(da_gross_mrr), 2) AS da_gross_mrr,
          ROUND(SUM(da_rvp_mrr), 2) AS da_rvp_mrr,
          ROUND(SUM(db_gross_mrr), 2) AS db_gross_mrr,
          ROUND(SUM(db_rvp_mrr), 2) AS db_rvp_mrr,
          ROUND(SUM(ge_gross_mrr), 2) AS ge_gross_mrr,
          ROUND(SUM(ge_rvp_mrr), 2) AS ge_rvp_mrr,
          ROUND(SUM(dadbai_gross_mrr), 2) AS dadbai_gross_mrr,
          ROUND(SUM(dadbai_rvp_mrr), 2) AS dadbai_rvp_mrr,
          ROUND(SUM(gcp_rvp_drr_avg), 2) AS gcp_rvp_drr_avg,
          ROUND(SUM(cloud_ai_rvp_drr_avg), 2) AS cloud_ai_rvp_drr_avg
        FROM `{PROJECT_ID}.{DATASET_ID}.project_monthly_revenue`
        WHERE project_id = @rpid
        GROUP BY year_month
        ORDER BY year_month ASC
        """

        query_daily = f"""
        SELECT
          CAST(usage_date AS STRING) AS usage_date,
          ROUND(SUM(gcp_gross_drr), 2) AS gcp_gross_drr,
          ROUND(SUM(gcp_rvp_drr), 2) AS gcp_rvp_drr,
          ROUND(SUM(cloud_ai_gross_drr), 2) AS cloud_ai_gross_drr,
          ROUND(SUM(cloud_ai_rvp_drr), 2) AS cloud_ai_rvp_drr,
          ROUND(SUM(da_gross_drr), 2) AS da_gross_drr,
          ROUND(SUM(da_rvp_drr), 2) AS da_rvp_drr,
          ROUND(SUM(db_gross_drr), 2) AS db_gross_drr,
          ROUND(SUM(db_rvp_drr), 2) AS db_rvp_drr,
          ROUND(SUM(ge_gross_drr), 2) AS ge_gross_drr,
          ROUND(SUM(ge_rvp_drr), 2) AS ge_rvp_drr,
          ROUND(SUM(dadbai_gross_drr), 2) AS dadbai_gross_drr,
          ROUND(SUM(dadbai_rvp_drr), 2) AS dadbai_rvp_drr,
          ROUND(SUM(gcp_rvp_drr_7d_avg), 2) AS gcp_rvp_drr_7d_avg,
          ROUND(SUM(cloud_ai_rvp_drr_7d_avg), 2) AS cloud_ai_rvp_drr_7d_avg
        FROM `{PROJECT_ID}.{DATASET_ID}.project_daily_runrate`
        WHERE project_id = @rpid
        GROUP BY usage_date
        ORDER BY usage_date ASC
        """

        f_m = _BQ_EXECUTOR.submit(lambda: [dict(row) for row in bq_client.query(query_monthly, job_config=jc_resolved).result()])
        f_d = _BQ_EXECUTOR.submit(lambda: [dict(row) for row in bq_client.query(query_daily, job_config=jc_resolved).result()])

        monthly_rows = f_m.result()
        for r in monthly_rows:
            for k, v in r.items():
                if hasattr(v, '__float__') and not isinstance(v, (bool, int)):
                    r[k] = float(v)

        daily_rows = f_d.result()
        for r in daily_rows:
            for k, v in r.items():
                if hasattr(v, '__float__') and not isinstance(v, (bool, int)):
                    r[k] = float(v)

        return {
            "found": True,
            "project": project_meta,
            "monthly_mrr": monthly_rows,
            "daily_drr": daily_rows,
        }

    return _get_cached(f"proj_trend:{pid.lower()}", _compute, force_refresh=(refresh == 1))

def _get_unauth_login_html(client_id: str) -> str:
    """Return a clean, zero-information login shell before authentication."""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Google SSO 安全认证</title>
  <script src="https://accounts.google.com/gsi/client" async defer></script>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      background-color: #f8fafd;
      color: #202124;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
    }}
    .gate-box {{
      background: #ffffff;
      border: 1px solid #dadce0;
      border-radius: 16px;
      padding: 40px 36px;
      width: 440px;
      max-width: 92vw;
      text-align: center;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.08);
    }}
    .logo-badge {{
      background: linear-gradient(135deg, #1a73e8, #0d47a1);
      color: #fff;
      font-weight: 700;
      font-size: 14px;
      padding: 6px 14px;
      border-radius: 8px;
      display: inline-block;
      margin-bottom: 16px;
    }}
    h2 {{ font-size: 20px; font-weight: 600; margin-bottom: 8px; }}
    p {{ color: #5f6368; font-size: 13px; line-height: 1.6; margin-bottom: 24px; }}
  </style>
</head>
<body>
  <div class="gate-box">
    <div class="logo-badge">🔒 企业门户安全认证</div>
    <h2>请登录以继续访问</h2>
    <p id="gateMsg">本系统受企业级单点登录（SSO）与安全授权策略保护，未登录前不展示任何页面信息。请使用授权的企业 Google 账号完成身份验证。</p>
    <div id="gbtn" style="display:flex; justify-content:center; margin-top:12px;"></div>
  </div>
  <script>
    function bootGsi() {{
      google.accounts.id.initialize({{
        client_id: {json.dumps(client_id)},
        ux_mode: 'popup',
        callback: function(resp) {{
          document.getElementById('gateMsg').textContent = '正在验证身份并签发安全会话，请稍候...';
          setTimeout(async function() {{
            try {{
              var r = await fetch('/api/auth/session', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                credentials: 'same-origin',
                body: JSON.stringify({{ credential: resp.credential }})
              }});
              if (r.status === 403) {{
                document.getElementById('gateMsg').textContent = '拒绝访问：当前账号未获得访问授权，请联系系统管理员开通权限';
                return;
              }}
              if (!r.ok) {{
                document.getElementById('gateMsg').textContent = '登录验证失败，请重试';
                return;
              }}
              var data = await r.json();
              if (data.session_token) {{
                sessionStorage.setItem('id_token', data.session_token);
              }}
              window.location.reload();
            }} catch (e) {{
              document.getElementById('gateMsg').textContent = '网络或验证异常，请重试';
            }}
          }}, 80);
        }}
      }});
      google.accounts.id.renderButton(document.getElementById('gbtn'), {{
        theme: 'outline',
        size: 'large',
        text: 'signin_with',
        shape: 'rectangular'
      }});
    }}
    if (window.google && google.accounts) {{ bootGsi(); }}
    else {{
      var t = setInterval(function() {{
        if (window.google && google.accounts) {{ clearInterval(t); bootGsi(); }}
      }}, 150);
    }}
  </script>
</body>
</html>"""


def _get_page_session_email(request: Request) -> str:
    if not APP_AUTH:
        return ADMIN_EMAIL
    gw_email = request.headers.get("x-authenticated-user-email", "").strip().lower()
    if gw_email and _user_ok(gw_email):
        return gw_email
    cookie_token = extract_cookie_token(request.headers.get("cookie", ""), COOKIE_NAME)
    if cookie_token:
        claims = verify_session_jwt(cookie_token)
        if claims:
            em = (claims.get("email") or "").strip().lower()
            if _user_ok(em):
                return em
    return ""


def _has_valid_page_session(request: Request) -> bool:
    return bool(_get_page_session_email(request))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    email = _get_page_session_email(request)
    if not email:
        return HTMLResponse(
            content=_get_unauth_login_html(OAUTH_CLIENT_ID),
            headers={
                "cross-origin-opener-policy": "same-origin-allow-popups",
                "cache-control": "no-store",
            },
        )
    html_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(
        content=html_content,
        headers={
            "cross-origin-opener-policy": "same-origin-allow-popups",
            "cache-control": "no-store",
        },
    )


@app.get("/releasenotes", response_class=HTMLResponse)
@app.get("/releasenote", response_class=HTMLResponse)
async def releasenotes_page(request: Request):
    email = _get_page_session_email(request)
    if not email:
        return HTMLResponse(
            content=_get_unauth_login_html(OAUTH_CLIENT_ID),
            headers={
                "cross-origin-opener-policy": "same-origin-allow-popups",
                "cache-control": "no-store",
            },
        )
    _log_audit_event(email, "PAGE_VIEW", "/releasenotes", "查看系统版本更新日志 (Release Notes)", request)
    html_path = os.path.join(os.path.dirname(__file__), "templates", "releasenotes.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(
        content=html_content,
        headers={
            "cross-origin-opener-policy": "same-origin-allow-popups",
            "cache-control": "no-store",
        },
    )


@app.get("/admin-audit", response_class=HTMLResponse)
async def admin_audit_page(request: Request):
    """Hidden admin-only access analytics page exclusively for liuchenggang@google.com."""
    email = _get_page_session_email(request)
    if not email:
        return HTMLResponse(
            content=_get_unauth_login_html(OAUTH_CLIENT_ID),
            headers={
                "cross-origin-opener-policy": "same-origin-allow-popups",
                "cache-control": "no-store",
            },
        )
    if not _is_admin(email):
        raise HTTPException(404, "Not Found")
    html_path = os.path.join(os.path.dirname(__file__), "templates", "admin_audit.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(
        content=html_content,
        headers={
            "cross-origin-opener-policy": "same-origin-allow-popups",
            "cache-control": "no-store",
        },
    )


@app.get("/api/admin/access-stats")
async def api_admin_access_stats(days: int = 30, user: str = Depends(require_admin)):
    """Return past 30 days user access analytics exclusively for liuchenggang@google.com."""
    days = max(1, min(days, 90))
    table_fqn = f"`{PROJECT_ID}.{DATASET_ID}.portal_access_audit_logs`"

    query_users = f"""
    SELECT
      LOWER(user_email) AS user_email,
      COUNT(*) AS total_events,
      COUNTIF(event_type = 'PAGE_VIEW' AND path_or_action = '/') AS dashboard_views,
      COUNTIF(event_type = 'PAGE_VIEW' AND path_or_action = '/releasenotes') AS releasenotes_views,
      COUNTIF(event_type = 'TAB_SWITCH') AS tab_switches,
      COUNTIF(event_type = 'DRILLDOWN') AS drilldowns,
      COUNTIF(event_type = 'AGENT_QUERY') AS agent_queries,
      COUNTIF(event_type = 'SSO_LOGIN') AS sso_logins,
      COUNTIF(event_type = 'CACHE_REFRESH') AS cache_refreshes,
      COUNT(DISTINCT event_date_cst) AS active_days,
      FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', MIN(event_time), 'Asia/Shanghai') AS first_seen_cst,
      FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', MAX(event_time), 'Asia/Shanghai') AS last_seen_cst
    FROM {table_fqn}
    WHERE event_date_cst >= DATE_SUB(CURRENT_DATE('Asia/Shanghai'), INTERVAL {days} DAY)
    GROUP BY 1
    ORDER BY total_events DESC
    """

    query_daily = f"""
    SELECT
      CAST(event_date_cst AS STRING) AS date_cst,
      COUNT(*) AS total_events,
      COUNTIF(event_type IN ('PAGE_VIEW', 'TAB_SWITCH')) AS page_views,
      COUNTIF(event_type = 'AGENT_QUERY') AS agent_queries,
      COUNTIF(event_type = 'DRILLDOWN') AS drilldowns,
      COUNT(DISTINCT LOWER(user_email)) AS unique_users
    FROM {table_fqn}
    WHERE event_date_cst >= DATE_SUB(CURRENT_DATE('Asia/Shanghai'), INTERVAL {days} DAY)
    GROUP BY 1
    ORDER BY 1 ASC
    """

    query_recent = f"""
    SELECT
      FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', event_time, 'Asia/Shanghai') AS event_time_cst,
      LOWER(user_email) AS user_email,
      event_type,
      path_or_action,
      detail,
      client_ip,
      user_agent
    FROM {table_fqn}
    WHERE event_date_cst >= DATE_SUB(CURRENT_DATE('Asia/Shanghai'), INTERVAL {days} DAY)
    ORDER BY event_time DESC
    LIMIT 200
    """

    f_users = _BQ_EXECUTOR.submit(lambda: [dict(r) for r in bq_client.query(query_users).result()])
    f_daily = _BQ_EXECUTOR.submit(lambda: [dict(r) for r in bq_client.query(query_daily).result()])
    f_recent = _BQ_EXECUTOR.submit(lambda: [dict(r) for r in bq_client.query(query_recent).result()])

    user_rows = f_users.result()
    daily_rows = f_daily.result()
    recent_rows = f_recent.result()

    # Merge with full ALLOWED_USERS roster so admin can also see which authorized users have 0 visits
    user_map = {r["user_email"]: r for r in user_rows}
    roster = []
    for allowed_email in sorted(ALLOWED_USERS):
        if allowed_email in user_map:
            item = dict(user_map[allowed_email])
            item["is_allowlisted"] = True
            item["active_status"] = "active"
            roster.append(item)
        else:
            roster.append({
                "user_email": allowed_email,
                "total_events": 0,
                "dashboard_views": 0,
                "releasenotes_views": 0,
                "tab_switches": 0,
                "drilldowns": 0,
                "agent_queries": 0,
                "sso_logins": 0,
                "cache_refreshes": 0,
                "active_days": 0,
                "first_seen_cst": "-",
                "last_seen_cst": "-",
                "is_allowlisted": True,
                "active_status": "inactive",
            })
    for r in user_rows:
        if r["user_email"] not in ALLOWED_USERS:
            item = dict(r)
            item["is_allowlisted"] = False
            item["active_status"] = "active"
            roster.append(item)

    roster.sort(key=lambda x: (x["total_events"], x["dashboard_views"]), reverse=True)

    total_events_30d = sum(r["total_events"] for r in user_rows)
    dashboard_views_30d = sum(r["dashboard_views"] + r["releasenotes_views"] + r["tab_switches"] for r in user_rows)
    agent_queries_30d = sum(r["agent_queries"] for r in user_rows)
    drilldowns_30d = sum(r["drilldowns"] for r in user_rows)
    unique_active_users = len([r for r in user_rows if r["total_events"] > 0])
    latest_event = recent_rows[0] if recent_rows else {}

    return {
        "admin_user": user,
        "window_days": days,
        "allowlist_total": len(ALLOWED_USERS),
        "summary": {
            "total_events": total_events_30d,
            "page_views": dashboard_views_30d,
            "unique_active_users": unique_active_users,
            "agent_queries": agent_queries_30d,
            "drilldowns": drilldowns_30d,
            "latest_time_cst": latest_event.get("event_time_cst", "-"),
            "latest_user": latest_event.get("user_email", "-"),
        },
        "users": roster,
        "daily_trend": daily_rows,
        "recent_logs": recent_rows,
    }


class AgentMessage(BaseModel):
    role: str
    content: str


class AgentChatRequest(BaseModel):
    question: str
    history: Optional[List[AgentMessage]] = None


BQCA_AGENT_ID = os.getenv("BQCA_AGENT_ID", "bhi-manu-2026-agent")
BQCA_AGENT_RESOURCE = f"projects/{PROJECT_ID}/locations/global/dataAgents/{BQCA_AGENT_ID}"
KNOWLEDGE_CATALOG_GLOSSARY = f"projects/{PROJECT_ID}/locations/global/glossaries/bhi-manu-2026-glossary"


def _get_authorized_session() -> ga_requests.AuthorizedSession:
    creds = _get_project_sa_credentials()
    return ga_requests.AuthorizedSession(creds)


@app.get("/api/agent/catalog")
async def api_agent_catalog(user: str = Depends(require_user)):
    """Return BQCA DataAgent & Knowledge Catalog metadata for the frontend governance badge."""
    return {
        "user": user,
        "engine": "BigQuery Conversational Analytics (BQCA) + Knowledge Catalog",
        "api_endpoint": "https://geminidataanalytics.googleapis.com/v1beta",
        "data_agent": BQCA_AGENT_RESOURCE,
        "knowledge_catalog_glossary": KNOWLEDGE_CATALOG_GLOSSARY,
        "governed_tables_count": 14,
        "governed_columns_count": 374,
        "glossary_terms_count": 9,
        "verified_queries_count": 9,
    }


@app.post("/api/agent/chat")
async def api_agent_chat(req: AgentChatRequest, request: Request, user: str = Depends(require_user)):
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(400, "Question cannot be empty")
    _log_audit_event(user, "AGENT_QUERY", "/api/agent/chat", f"AI 提问: {question[:150]}", request)

    # Build multi-turn context prompt if conversation history exists
    full_prompt = question
    if req.history:
        recent_turns = []
        for msg in req.history[-6:]:
            role_label = "用户" if msg.role == "user" else "BQCA Agent"
            content_str = (msg.content or "").strip()
            if content_str:
                recent_turns.append(f"{role_label}: {content_str[:600]}")
        if recent_turns:
            history_block = "\n".join(recent_turns)
            full_prompt = (
                f"【多轮对话上下文参考】\n{history_block}\n\n"
                f"【当前最新查询问题】\n{question}"
            )

    chat_url = f"https://geminidataanalytics.googleapis.com/v1beta/projects/{PROJECT_ID}/locations/global:chat"
    headers = {
        "X-Goog-User-Project": PROJECT_ID,
        "Content-Type": "application/json",
    }
    payload = {
        "messages": [
            {
                "userMessage": {
                    "text": full_prompt,
                }
            }
        ],
        "dataAgentContext": {
            "dataAgent": BQCA_AGENT_RESOURCE,
            "contextVersion": "PUBLISHED",
        },
    }

    try:
        session = _get_authorized_session()
        resp = session.post(chat_url, headers=headers, json=payload, timeout=120)
        if resp.status_code != 200:
            raise HTTPException(
                502,
                f"BQCA API returned HTTP {resp.status_code}: {resp.text[:500]}",
            )

        chunks = resp.json()
        if not isinstance(chunks, list):
            chunks = [chunks]

        thoughts: List[Dict[str, str]] = []
        executed_queries: List[Dict[str, Any]] = []
        final_parts: List[str] = []
        followup_questions: List[str] = []

        pending_explanation = ""
        pending_sql = ""
        pending_job_id = ""

        def _flush_pending_sql(rows_data: Optional[List[Dict[str, Any]]] = None, cols_list: Optional[List[str]] = None):
            nonlocal pending_explanation, pending_sql, pending_job_id
            if not pending_sql:
                return
            r_list = rows_data if rows_data is not None else []
            c_list = cols_list if cols_list else (list(r_list[0].keys()) if r_list else [])
            executed_queries.append({
                "explanation": pending_explanation or "BQCA + Knowledge Catalog 语义 SQL 查询",
                "sql": pending_sql,
                "columns": c_list,
                "rows": r_list[:100],
                "row_count": len(r_list),
                "job_id": pending_job_id,
            })
            pending_explanation = ""
            pending_sql = ""
            pending_job_id = ""

        for chunk in chunks:
            sm = chunk.get("systemMessage", {})
            if not sm:
                continue

            # 1. Text messages: THOUGHT, PROGRESS, FINAL_RESPONSE, FOLLOWUP_QUESTIONS
            if "text" in sm:
                t_obj = sm["text"]
                t_type = t_obj.get("textType", "")
                parts = [p for p in t_obj.get("parts", []) if isinstance(p, str) and p.strip()]
                if t_type == "THOUGHT" and parts:
                    title = parts[0].strip() if len(parts) > 1 else "BQCA 语义推理"
                    body = "\n".join(parts[1:]).strip() if len(parts) > 1 else parts[0].strip()
                    thoughts.append({"title": title, "content": body})
                elif t_type == "FINAL_RESPONSE" and parts:
                    final_parts.extend(parts)
                elif t_type == "FOLLOWUP_QUESTIONS" and parts:
                    followup_questions.extend(parts)

            # 2. Data messages: query, generatedSql, bigQueryJob, result
            if "data" in sm:
                d_obj = sm["data"]
                if "query" in d_obj:
                    q_meta = d_obj["query"]
                    pending_explanation = q_meta.get("question") or q_meta.get("name") or pending_explanation
                if "generatedSql" in d_obj:
                    if pending_sql:
                        _flush_pending_sql()
                    pending_sql = d_obj["generatedSql"].strip()
                if "bigQueryJob" in d_obj:
                    job_meta = d_obj["bigQueryJob"]
                    pending_job_id = job_meta.get("jobId", "")
                if "result" in d_obj:
                    res_meta = d_obj["result"]
                    rows = res_meta.get("data", [])
                    schema_fields = res_meta.get("schema", {}).get("fields", [])
                    cols = [f.get("name", "") for f in schema_fields if f.get("name")]
                    _flush_pending_sql(rows_data=rows, cols_list=cols)

        # Flush any trailing generatedSql if no result chunk followed
        if pending_sql:
            _flush_pending_sql()

        answer_text = "\n\n".join(final_parts).strip()
        if not answer_text:
            answer_text = "已完成 **BQCA + Knowledge Catalog** 数据查询，请查看下方生成的 BigQuery SQL 与结果明细。"

        return {
            "user": user,
            "engine": "BQCA + Knowledge Catalog",
            "data_agent": BQCA_AGENT_RESOURCE,
            "knowledge_catalog_glossary": KNOWLEDGE_CATALOG_GLOSSARY,
            "answer": answer_text,
            "thoughts": thoughts,
            "sql_queries": executed_queries,
            "followup_questions": followup_questions[:4],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"BQCA + Knowledge Catalog execution error: {e}")



