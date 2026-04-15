# Plan: Admin JWT Auth

## Context
Admin API routes (`/admin/*`) and the admin frontend (`admin/index.html`) are completely unprotected. The goal is to add a simple password → short-lived JWT layer to hide admin tools from the public, while establishing a pattern that can be swapped for OAuth (PKCE) later without touching the rest of the stack.

## Approach
- **Backend:** `POST /admin/auth/token` accepts a password from env, returns a signed JWT (8h expiry). All `/admin/*` routes require a valid Bearer JWT via a shared FastAPI dependency.
- **Edge throttle:** nginx rate-limits `POST /api/admin/auth/token` per source IP before forwarding to the API.
- **Lockout:** Failed login attempts are tracked per source IP in process memory. After `ADMIN_LOGIN_MAX_FAILURES` consecutive failures, that IP is blocked for `ADMIN_LOGIN_LOCKOUT_SECONDS`. A successful login resets the counter.
- **Frontend:** Login gate renders `<AdminLogin />` when no valid token is in `sessionStorage`; on success stores the token and shows `<AdminPage />`. All `adminApi.ts` calls attach `Authorization: Bearer <token>`; 401s clear the token and redirect to login.

---

## Backend Changes

### 1. `backend/pyproject.toml`
Add to `[project.dependencies]`:
```
"PyJWT>=2.9.0",
```

### 2. `backend/src/ot_backend/core/config.py`
Add two getter functions following the existing `os.getenv` pattern:
```python
def admin_password() -> str | None:
    return os.getenv("ADMIN_PASSWORD")

def admin_jwt_secret() -> str | None:
    return os.getenv("ADMIN_JWT_SECRET")
```

### 3. New file: `backend/src/ot_backend/api/admin_auth.py`
Contains:
- `create_admin_token()` — signs a JWT with `sub="admin"`, 8h expiry, HS256
- `AdminTokenDep` — FastAPI `Depends` using `HTTPBearer`; decodes + validates the JWT; raises `401` on any failure
- Imports `admin_password()` and `admin_jwt_secret()` from `core/config`
- If `ADMIN_PASSWORD` or `ADMIN_JWT_SECRET` are not set, the auth endpoint returns 503

### 4. `backend/src/ot_backend/api/main.py`
- Add `POST /admin/auth/token` route (not protected):
  ```
  Body: { "password": str }
  Returns: { "access_token": str, "token_type": "bearer", "expires_in": 28800 }
  ```
  Checks password against `admin_password()`, returns signed JWT or 401.
- Add per-IP lockout checks before password verification:
  - wrong password increments the failure counter for the request IP
  - hitting the threshold returns `429 Too Many Requests` with `Retry-After`
  - successful login clears prior failures for that IP
  - request IP comes from `X-Real-IP`, then `X-Forwarded-For`, then the socket peer
- Inject `AdminTokenDep` on all existing `/admin/*` route handlers as an additional `Depends` parameter (unused in function body — `_: None = Depends(admin_token_dep)`).

---

## Frontend Changes

### 5. New file: `frontend/src/admin/AdminLogin.tsx`
Simple form component:
- Password input + submit button
- On submit: `POST /api/admin/auth/token` with password
- On success: store token in `sessionStorage("admin_token")`, call `onSuccess()` prop
- On failure: show inline error message
- Styled with existing Tailwind classes from the admin page

### 6. `frontend/src/admin-main.tsx`
Wrap `<AdminApp />` with auth state check:
- Read `sessionStorage("admin_token")` on mount
- If absent → render `<AdminLogin onSuccess={() => setAuthed(true)} />`
- If present → render `<AdminPage />`
- Pass `onLogout` callback to `AdminPage` that clears the token and resets auth state

### 7. `frontend/src/lib/adminApi.ts`
- Add `getAdminToken()` helper that reads `sessionStorage("admin_token")`
- Add `Authorization: Bearer <token>` header to all fetch calls
- On `401` response: clear the token from sessionStorage and `window.location.reload()` to force re-render to login gate

---

## Environment Variables Required
| Variable | Notes |
|---|---|
| `ADMIN_PASSWORD` | The password checked at `/admin/auth/token` |
| `ADMIN_JWT_SECRET` | HS256 signing secret — generate with `openssl rand -hex 32` |
| `ADMIN_LOGIN_MAX_FAILURES` | Optional consecutive failed login threshold per IP (default `5`) |
| `ADMIN_LOGIN_LOCKOUT_SECONDS` | Optional lockout duration after threshold is hit (default `900`) |

Add both to Railway env config. Do not commit values.

---

## Critical Files
| File | Change |
|---|---|
| `backend/pyproject.toml` | Add PyJWT dep |
| `backend/src/ot_backend/core/config.py` | Add env var getters |
| `backend/src/ot_backend/api/main.py` | Add auth route + inject dep on admin handlers |
| `frontend/src/admin-main.tsx` | Auth gate (login vs dashboard) |
| `frontend/src/lib/adminApi.ts` | Attach Bearer token, handle 401 |
| `backend/src/ot_backend/api/admin_auth.py` | **New** — JWT creation + FastAPI dep |
| `frontend/src/admin/AdminLogin.tsx` | **New** — login form component |

---

## Verification
1. **Backend tests** — add to `tests/test_api.py`:
   - `POST /admin/auth/token` with wrong password → 401
   - `POST /admin/auth/token` with correct password → 200 + `access_token`
   - repeated wrong passwords from one IP → `429` + `Retry-After`
   - `GET /admin/semantic-models` with no token → 401
   - `GET /admin/semantic-models` with valid token → 200
2. **Manual test** — `docker compose up`, navigate to `/admin/`, verify login form appears, log in with `ADMIN_PASSWORD`, verify admin dashboard loads.
3. **Expiry test** — temporarily reduce JWT expiry to 5s in dev, confirm 401 is triggered and login is re-shown.

---

## Future: OAuth Migration Path
When ready for real user logins, replace `POST /admin/auth/token` with an OAuth PKCE flow (GitHub, Google, Auth0). The rest of the stack — `AdminTokenDep`, `adminApi.ts` Bearer attachment, and the login gate — stays identical.

## Operational Notes
- The current lockout store is per-process memory. If you scale the API horizontally, each process maintains its own counters until this is moved into shared storage.
- In production behind a proxy, set `X-Real-IP` from the socket peer and sanitize incoming forwarded-IP headers before they reach the API.
