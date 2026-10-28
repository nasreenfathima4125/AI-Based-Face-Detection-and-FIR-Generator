# AI-Based-Face-Detection-and-FIR-Generator
The Integrated AI Surveillance and FIR Assistance System is an academic prototype focused on FIR assistance. Citizens can submit complaints, and an authorized application reviewer can inspect, edit, and approve a Malayalam draft prepared from a fixed template. The prototype does not provide face recognition, CCTV processing, or LLM-generated drafts, and an in-application approval is not official FIR registration.

### Citizen complaint languages

The complaint conversation, guided form, validation feedback, review screen,
submission confirmation, public status tracking, and citizen dashboard support English, Malayalam, and Hindi. Changing
the selected language keeps entered complaint answers and displays category
names in the chosen language while retaining the existing language-independent
category values in storage. Citizen-supplied names, locations, descriptions,
and other factual answers are preserved as entered; the interface does not
translate them. The FIR draft is still produced by the existing deterministic
Malayalam template and is not an AI translation or an officially registered FIR.

## Running the FIR assistance application

Persistent sign-in is provided by a same-origin authentication gateway in front
of Streamlit. The gateway issues an opaque `HttpOnly`, `SameSite=Lax` cookie;
Streamlit validates its hash against the SQLite `auth_sessions` table and loads
the current account role from `users` on each rerun. Sessions expire after 12
hours by default (`FIR_AUTH_SESSION_TTL_SECONDS` can be set from 300 seconds to
30 days). Signing out revokes the database session and clears the cookie.

Do not expose the Streamlit port or gateway port directly. Route the
browser-facing origin through a reverse proxy that sends `/auth/*` to the
gateway and all other paths, including WebSockets, to Streamlit.
[Caddyfile.example](./Caddyfile.example) is the recommended local Windows
configuration. Caddy supports WebSocket proxying and forwards request cookies
and response `Set-Cookie` headers without additional directives.
[nginx-auth.conf.example](./nginx-auth.conf.example) is an alternative for
environments that already use Nginx.

### Public complaint-status lookup limits

The public tracking form allows **10 complete status lookups per client IP in
a fixed 15-minute window** by default. Configure the threshold with
`FIR_PUBLIC_LOOKUP_RATE_LIMIT` (1–100) and the window with
`FIR_PUBLIC_LOOKUP_RATE_WINDOW_SECONDS` (1–86400). Successful and failed
lookups both count. The limit is stored in the configured SQLite database, so
Streamlit reruns, browser sessions, and application workers sharing that
database use the same counter. Expired rows are cleaned up during subsequent
lookups.

The database stores an HMAC digest of the client IP, not the IP or contact
number. The HMAC uses the existing `FIR_OTP_HMAC_SECRET`. Behind the included
reverse proxy, set `FIR_AUTH_TRUST_PROXY=true` and keep the Streamlit and
gateway listeners restricted to loopback. The application uses the last
address appended to `X-Forwarded-For`; the included Caddy proxy sets or
augments forwarded headers while ignoring untrusted incoming values by
default. If no trusted client address is available, requests share a
fail-closed bucket, which can restrict multiple local users together.

This application-level limit reduces repeated lookup attempts but is not a
production-grade abuse-prevention system. Shared public IPs can share a limit,
and distributed clients can use separate limits. Public deployments need a
trusted proxy configuration and additional edge-level abuse controls.

For local Windows testing, install Caddy once from the verified WinGet package:

```powershell
winget install --id CaddyServer.Caddy --exact --source winget
```

In the repository root, create a unique temporary database and a private
development environment file. Do not use `fir_system.db`:

The local setup below explicitly enables fictional demonstration accounts so
the police and administrator workflows can be tested. The flag is opt-in;
leave it disabled for any database that may contain real records. These demo
roles do not verify real-world police employment or administrator identity.

```powershell
$testRoot = Join-Path $env:TEMP ("fir-assistance-auth-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$randomBytes = New-Object byte[] 48
$rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider
$rng.GetBytes($randomBytes)
$rng.Dispose()
$otpSecret = [Convert]::ToBase64String($randomBytes)
$environmentFile = Join-Path $testRoot "local-auth.env"
@"
FIR_SYSTEM_DB_PATH=$(Join-Path $testRoot "fir_system_test.sqlite3")
FIR_OTP_HMAC_SECRET=$otpSecret
SMS_PROVIDER=mock
FIR_ENABLE_DEMO_ACCOUNTS=true
FIR_AUTH_SESSION_TTL_SECONDS=43200
FIR_AUTH_COOKIE_SECURE=false
FIR_AUTH_TRUST_PROXY=true
FIR_AUTH_ALLOWED_HOSTS=localhost,127.0.0.1
FIR_AUTH_GATEWAY_HOST=127.0.0.1
FIR_AUTH_GATEWAY_PORT=8502
"@ | Set-Content -Path $environmentFile -Encoding ascii
Write-Output "Environment file: $environmentFile"
```

Copy the printed environment-file path. Start each service in its own PowerShell
terminal from the repository root, setting `$environmentFile` to that exact
path and loading its values in **each** terminal:

**Terminal 1 — authentication gateway**

```powershell
$environmentFile = "C:\Users\<you>\AppData\Local\Temp\fir-assistance-auth-<id>\local-auth.env"
Get-Content $environmentFile | ForEach-Object {
    $parts = $_.Split('=', 2)
    Set-Item -Path "Env:$($parts[0])" -Value $parts[1]
}
.\.venv\Scripts\python.exe auth_gateway.py
```

**Terminal 2 — Streamlit, bound to loopback**

```powershell
$environmentFile = "C:\Users\<you>\AppData\Local\Temp\fir-assistance-auth-<id>\local-auth.env"
Get-Content $environmentFile | ForEach-Object {
    $parts = $_.Split('=', 2)
    Set-Item -Path "Env:$($parts[0])" -Value $parts[1]
}
.\.venv\Scripts\streamlit.exe run app.py `
    --server.address 127.0.0.1 `
    --server.port 8501 `
    --server.enableCORS true `
    --server.corsAllowedOrigins http://localhost:8500 `
    --server.enableXsrfProtection true `
    --server.allowedHosts localhost
```

**Terminal 3 — Caddy reverse proxy**

```powershell
& "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\CaddyServer.Caddy_Microsoft.Winget.Source_8wekyb3d8bbwe\caddy.exe" run --config .\Caddyfile.example --adapter caddyfile
```

Open `http://localhost:8500`. The generated path is also the location of the
isolated test database. Keep the environment file private and remove the
temporary directory only after stopping all three services.

For HTTPS deployments, terminate TLS at the trusted reverse proxy, forward
`X-Forwarded-Proto`, set `FIR_AUTH_COOKIE_SECURE=true`, and configure
`FIR_AUTH_ALLOWED_HOSTS` to the actual public host. Bind both backend services
to loopback or a private network and restrict access to the proxy. The included
Caddy and Nginx configurations are for local development only; neither is a
production TLS configuration.
