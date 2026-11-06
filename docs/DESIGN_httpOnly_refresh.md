# Design: refresh token in an httpOnly cookie

**Status:** built, switched off (F-15 / AUTH-001). Until it is switched on,
both tokens are kept in the browser's `localStorage`, where any script
running on the page can read them. The Content-Security-Policy is now
enforcing, which is the main guard against such a script.

## Switching it on (owner)

Only after the prerequisites below (one shared domain):

1. Render: `AUTH_REFRESH_COOKIE=1`, and `AUTH_REFRESH_COOKIE_DOMAIN` = the
   API's host (e.g. `api.housemaster.example`) or blank. This also turns on
   `CORS_ALLOW_CREDENTIALS`. Deploy.
2. Vercel: `VITE_REFRESH_COOKIE=1` (Production), and redeploy.

Both switches go on together: the backend alone would leave the app without
a refresh token, the frontend alone would send cookies the API refuses.
Undo by removing both. People signed in at the time sign in once more.

Built as: `accounts/refresh_cookie.py` (middleware: moves `refresh` from any
sign-in answer into the cookie, reads it back for `/api/token/refresh/` and
`/api/token/logout/`, requires `X-Requested-With: HouseMaster` and an allowed
`Origin`), tests in `accounts/test_refresh_cookie.py`; frontend `src/api.js`
(`COOKIE_MODE`), test `src/refreshCookie.test.js`.

## Goal

Keep the long-lived refresh token where page scripts can't read it, so a
future cross-site-scripting bug can't steal a session that outlives the
page. The short-lived access token (60 minutes) stays in memory only.

## Why not now

The frontend (`*.vercel.app`) and the API (`*.onrender.com`) are on
different sites. A cookie set by the API is then a third-party cookie from
the frontend's point of view: it needs `SameSite=None; Secure`, and Safari
(and increasingly Chrome) blocks or partitions third-party cookies. Users
would be signed out at random. It only works reliably when both are on one
registrable domain.

## Prerequisites

1. A custom domain with both parts under it, for example
   `app.housemaster.example` (Vercel) and `api.housemaster.example` (Render).
   Both use HTTPS (Vercel and Render issue certificates automatically).
2. `CORS_ALLOWED_ORIGINS` = `https://app.housemaster.example`, and
   `CORS_ALLOW_CREDENTIALS = True` on the backend.
3. `VITE_API_BASE_URL` = `https://api.housemaster.example`, and the CSP's
   `connect-src` updated to it.

## Design

**Cookie**, set by `/api/token/`, `/api/token/refresh/` and the invite /
sign-up endpoints that log someone in:

```
Set-Cookie: hm_refresh=<token>; HttpOnly; Secure; SameSite=Strict;
            Path=/api/token/; Domain=api.housemaster.example; Max-Age=259200
```

- `HttpOnly`: page scripts can't read it.
- `SameSite=Strict`: app and API are same-site under the shared domain, so
  the browser still sends it, and it is never sent from another site.
- `Path=/api/token/`: sent only to the refresh and logout endpoints, not
  with every request.
- `Max-Age` = `JWT_REFRESH_TOKEN_DAYS`.

**Access token:** returned in the JSON body as now, kept in a JavaScript
variable (not `localStorage`). A page reload gets a new one from
`/api/token/refresh/` using the cookie.

**Refresh:** `POST /api/token/refresh/` with no body reads the cookie,
rotates as today (blacklist the old one, set a new cookie) and returns a
new access token. Logout moves to `POST /api/token/logout/` (inside the cookie's path; `/api/logout/` stays as an alias during the migration) and blacklists the cookie's token
and clears the cookie.

**CSRF:** the refresh and logout endpoints accept a cookie, so they need
CSRF protection. With `SameSite=Strict` other sites can't make the
browser send the cookie; as a second guard, require a custom header
(`X-Requested-With: HouseMaster`), which a cross-site form can't add, and
check `Origin` against `CORS_ALLOWED_ORIGINS`. All other endpoints keep
using the `Authorization: Bearer` header and are unaffected.

## Migration plan

1. Backend accepts the refresh token from either the body (as today) or
   the cookie, and sets the cookie on every login and refresh. Deploy.
2. Frontend stops storing the refresh token: it relies on the cookie and
   keeps the access token in memory. It deletes any old
   `housemaster_tokens` entry from `localStorage`. Deploy.
3. After `JWT_REFRESH_TOKEN_DAYS` have passed (every old body-based refresh
   token has expired), the backend stops accepting refresh tokens in the
   body.

Each step is safe on its own, and step 1 can be rolled back at any time.

## Tests to write when building it

- Login sets an `HttpOnly; Secure; SameSite=Strict` cookie scoped to
  `/api/token/`.
- Refresh with the cookie rotates it; replaying the old one fails.
- Refresh without the custom header or from a foreign `Origin` is refused.
- Logout clears the cookie and blacklists the token.
- The frontend never writes a refresh token to `localStorage`.
