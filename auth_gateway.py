"""Same-origin HTTP endpoints for login, registration, and logout.

Run this gateway behind a reverse proxy that exposes only its /auth/ routes.
The Streamlit port must remain bound to localhost and must not be public.
"""

from datetime import datetime, timezone
from email.utils import format_datetime
from html import escape
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import sqlite3
from typing import Optional
from urllib.parse import parse_qs, urlsplit

import auth_sessions
import database

_MAX_FORM_BYTES = 16_384
_ROLE_DASHBOARD_PATHS = {
    "citizen": "/citizen_dashboard",
    "police": "/police_dashboard",
    "admin": "/admin_dashboard",
}
_STYLE = """
<style>
    :root { color-scheme: light; }
    body {
        margin: 0;
        background: #F3EBDD;
        color: #493A2D;
        font: 16px/1.55 Inter, system-ui, sans-serif;
    }
    main {
        box-sizing: border-box;
        max-width: 520px;
        margin: 8vh auto;
        padding: 32px;
        background: #FFFCF6;
        border: 1px solid #DED3C1;
        border-radius: 10px;
    }
    h1 { margin-top: 0; font-size: 1.8rem; }
    label { display: block; margin: 16px 0 6px; font-weight: 600; }
    input {
        box-sizing: border-box;
        width: 100%;
        min-height: 42px;
        padding: 9px 11px;
        border: 1px solid #BFB3A2;
        border-radius: 7px;
        background: #FFFCF6;
        color: #493A2D;
        font: inherit;
    }
    button {
        width: 100%;
        min-height: 44px;
        margin-top: 22px;
        border: 0;
        border-radius: 7px;
        background: #356B68;
        color: #FFFCF6;
        font: inherit;
        font-weight: 650;
        cursor: pointer;
    }
    a { color: #275250; }
    .message { margin: 16px 0; }
    .error { color: #8C3832; }
    .field-error { margin: 4px 0 0; font-size: .9rem; }
    .form-switch { margin-top: 20px; font-size: .92rem; }
    :focus-visible { outline: 3px solid #6E9B96; outline-offset: 2px; }
</style>
"""


def _page(title: str, content: str) -> bytes:
    safe_title = escape(title)
    document = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{safe_title}</title>{_STYLE}</head><body><main>"
        "<div><strong>FIR Assistance System</strong></div>"
        f"<h1>{safe_title}</h1>{content}</main></body></html>"
    )
    return document.encode("utf-8")


def _login_form(message: str = "", error: bool = False) -> bytes:
    message_html = ""
    if message:
        message_html = (
            f'<p class="message{" error" if error else ""}" role="alert">'
            f"{escape(message)}</p>"
        )
    content = (
        "<p>Use your registered email address and password.</p>"
        f"{message_html}"
        '<form method="post" action="/auth/login" autocomplete="on">'
        '<label for="email">Email address</label>'
        '<input id="email" name="email" type="email" autocomplete="username" '
        'required maxlength="254">'
        '<label for="password">Password</label>'
        '<input id="password" name="password" type="password" '
        'autocomplete="current-password" required maxlength="1024">'
        '<button type="submit">Sign In</button></form>'
        '<p class="form-switch">Don\'t have an account? '
        '<a href="/auth/signup">Create Account</a></p>'
    )
    return _page("Sign In", content)


def _signup_form(
    message: str = "",
    error: bool = False,
    errors: Optional[dict[str, str]] = None,
    values: Optional[dict[str, str]] = None,
) -> bytes:
    errors = errors or {}
    values = values or {}

    def field_error(field: str) -> str:
        field_message = errors.get(field)
        if not field_message:
            return ""
        return (
            f'<p class="message error field-error" id="{field}-error" '
            f'role="alert">{escape(field_message)}</p>'
        )

    def field_attributes(field: str) -> str:
        if field not in errors:
            return ""
        return f' aria-invalid="true" aria-describedby="{field}-error"'

    message_html = ""
    if message:
        message_html = (
            f'<p class="message{" error" if error else ""}" role="alert">'
            f"{escape(message)}</p>"
        )
    content = (
        "<p>Account registration is optional for complaint submission.</p>"
        f"{message_html}"
        '<form method="post" action="/auth/signup" autocomplete="on">'
        '<label for="full_name">Full name</label>'
        f'<input id="full_name" name="full_name" autocomplete="name" required '
        f'maxlength="200" value="{escape(values.get("full_name", ""), quote=True)}"'
        f'{field_attributes("full_name")}>'
        f'{field_error("full_name")}'
        '<label for="contact_number">Phone number</label>'
        '<input id="contact_number" name="contact_number" autocomplete="tel" '
        f'maxlength="40" value="{escape(values.get("contact_number", ""), quote=True)}"'
        f'{field_attributes("contact_number")}>'
        f'{field_error("contact_number")}'
        '<label for="email">Email address</label>'
        f'<input id="email" name="email" type="email" autocomplete="email" '
        f'required maxlength="254" value="{escape(values.get("email", ""), quote=True)}"'
        f'{field_attributes("email")}>'
        f'{field_error("email")}'
        '<label for="password">Create a password</label>'
        '<input id="password" name="password" type="password" '
        f'autocomplete="new-password" required minlength="8" maxlength="1024"'
        f'{field_attributes("password")}>'
        f'{field_error("password")}'
        '<label for="confirm_password">Confirm password</label>'
        '<input id="confirm_password" name="confirm_password" type="password" '
        f'autocomplete="new-password" required minlength="8" maxlength="1024"'
        f'{field_attributes("confirm_password")}>'
        f'{field_error("confirm_password")}'
        '<button type="submit">Create Account</button></form>'
        '<p class="form-switch">Already have an account? '
        '<a href="/auth/login">Sign In</a></p>'
    )
    return _page("Create Account", content)


class AuthGatewayHandler(BaseHTTPRequestHandler):
    """Handles credential forms without sending passwords through Streamlit."""

    protocol_version = "HTTP/1.0"

    def log_message(self, _format_string: str, *_args: object) -> None:
        # Default request logs can include user-controlled values; omit them.
        del _format_string, _args
        return

    def _allowed_hosts(self) -> set[str]:
        configured = os.environ.get(
            "FIR_AUTH_ALLOWED_HOSTS",
            "localhost,127.0.0.1",
        )
        return {
            host.strip().lower()
            for host in configured.split(",")
            if host.strip()
        }

    def _request_host(self) -> Optional[str]:
        header_value = self.headers.get("Host", "")
        try:
            return urlsplit(f"//{header_value}").hostname
        except ValueError:
            return None

    def _public_scheme(self) -> str:
        trust_proxy = os.environ.get(
            "FIR_AUTH_TRUST_PROXY",
            "false",
        ).strip().lower() == "true"
        if trust_proxy:
            forwarded_proto = self.headers.get(
                "X-Forwarded-Proto",
                "",
            ).split(",", 1)[0].strip().lower()
            if forwarded_proto in {"http", "https"}:
                return forwarded_proto
        return "http"

    def _valid_request_origin(self) -> bool:
        request_host = self.headers.get("Host", "")
        hostname = self._request_host()
        if hostname is None or hostname.lower() not in self._allowed_hosts():
            return False

        origin_value = self.headers.get("Origin")
        if not origin_value:
            return False
        try:
            origin = urlsplit(origin_value)
        except ValueError:
            return False
        return (
            origin.scheme == self._public_scheme()
            and origin.netloc.lower() == request_host.lower()
            and origin.path == ""
            and not origin.query
            and not origin.fragment
        )

    def _send_response(
        self,
        status: int,
        body: bytes = b"",
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; "
            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
        )
        if auth_sessions.cookie_secure_enabled() or (
            self._public_scheme() == "https"
        ):
            self.send_header(
                "Strict-Transport-Security",
                "max-age=31536000",
            )
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _send_page(
        self,
        status: int,
        title: str,
        content: str,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        self._send_response(status, _page(title, content), headers)

    def _send_redirect(self, headers: Optional[dict[str, str]] = None) -> None:
        response_headers = {"Location": "/"}
        response_headers.update(headers or {})
        self._send_response(303, headers=response_headers)

    def _read_form(self) -> Optional[dict[str, str]]:
        content_type = self.headers.get("Content-Type", "")
        if content_type.partition(";")[0].strip().lower() != (
            "application/x-www-form-urlencoded"
        ):
            return None
        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return None
        if not 0 <= content_length <= _MAX_FORM_BYTES:
            return None
        raw_body = self.rfile.read(content_length)
        try:
            parsed = parse_qs(
                raw_body.decode("utf-8"),
                keep_blank_values=True,
                max_num_fields=12,
            )
        except (UnicodeDecodeError, ValueError):
            return None
        return {
            key: values[0]
            for key, values in parsed.items()
            if values
        }

    def _cookie_token(self) -> Optional[str]:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except (ValueError, KeyError):
            return None
        morsel = cookie.get(auth_sessions.SESSION_COOKIE_NAME)
        return morsel.value if morsel is not None else None

    def _session_cookie(self, token: str, expires_at: datetime) -> str:
        cookie = SimpleCookie()
        cookie[auth_sessions.SESSION_COOKIE_NAME] = token
        morsel = cookie[auth_sessions.SESSION_COOKIE_NAME]
        morsel["path"] = "/"
        morsel["httponly"] = True
        morsel["samesite"] = "Lax"
        morsel["max-age"] = str(auth_sessions.session_ttl_seconds())
        morsel["expires"] = format_datetime(
            expires_at.astimezone(timezone.utc),
            usegmt=True,
        )
        if auth_sessions.cookie_secure_enabled() or (
            self._public_scheme() == "https"
        ):
            morsel["secure"] = True
        return morsel.OutputString()

    def _clear_session_cookie(self) -> str:
        cookie = SimpleCookie()
        cookie[auth_sessions.SESSION_COOKIE_NAME] = ""
        morsel = cookie[auth_sessions.SESSION_COOKIE_NAME]
        morsel["path"] = "/"
        morsel["httponly"] = True
        morsel["samesite"] = "Lax"
        morsel["max-age"] = "0"
        morsel["expires"] = "Thu, 01 Jan 1970 00:00:00 GMT"
        if auth_sessions.cookie_secure_enabled() or (
            self._public_scheme() == "https"
        ):
            morsel["secure"] = True
        return morsel.OutputString()

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if self._request_host() is None or (
            self._request_host().lower() not in self._allowed_hosts()
        ):
            self._send_page(400, "Request unavailable", "<p>Request unavailable.</p>")
        elif path == "/auth/health":
            self._send_response(200, b"ok")
        elif path == "/auth/login":
            query = parse_qs(urlsplit(self.path).query)
            registered = query.get("registered") == ["1"]
            message = (
                "Your account has been created. Sign in to continue."
                if registered
                else ""
            )
            self._send_response(200, _login_form(message))
        elif path == "/auth/signup":
            self._send_response(200, _signup_form())
        elif path == "/auth/logout":
            self._send_page(
                200,
                "Sign out",
                '<p>Sign out of your current account on this browser.</p>'
                '<form method="post" action="/auth/logout">'
                '<button type="submit">Sign out</button></form>'
                '<p><a href="/">Return to the application</a></p>',
            )
        else:
            self._send_page(
                404,
                "Page not found",
                '<p><a href="/auth/login">Sign in</a></p>',
            )

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if self._request_host() is None or (
            self._request_host().lower() not in self._allowed_hosts()
        ):
            self._send_page(400, "Request unavailable", "<p>Request unavailable.</p>")
            return
        if not self._valid_request_origin():
            self._send_page(
                403,
                "Request unavailable",
                "<p>This request could not be verified. Return and try again.</p>",
            )
            return
        form_data = self._read_form()
        if form_data is None:
            self._send_page(
                400,
                "Request unavailable",
                "<p>Check the submitted form and try again.</p>",
            )
            return

        if path == "/auth/login":
            self._handle_login(form_data)
        elif path == "/auth/signup":
            self._handle_signup(form_data)
        elif path == "/auth/logout":
            self._handle_logout()
        else:
            self._send_page(
                404,
                "Page not found",
                '<p><a href="/auth/login">Sign in</a></p>',
            )

    def _handle_login(self, form_data: dict[str, str]) -> None:
        email = form_data.get("email", "")
        password = form_data.get("password", "")
        if (
            not email.strip()
            or not password
            or len(email) > 254
            or len(password) > 1024
        ):
            self._send_response(
                400,
                _login_form("Enter your registered email and password.", True),
            )
            return
        try:
            success, _, user = database.authenticate_user(
                email=email,
                password=password,
            )
            if not success or user is None:
                self._send_response(
                    401,
                    _login_form("Unable to sign in. Check your details and try again.", True),
                )
                return
            dashboard_path = _ROLE_DASHBOARD_PATHS.get(user["role"])
            if dashboard_path is None:
                self._send_page(
                    403,
                    "Dashboard unavailable",
                    "<p>This account does not have an available dashboard.</p>",
                )
                return
            token, expires_at = auth_sessions.create_session(user["id"])
        except (sqlite3.Error, ValueError):
            self._send_page(
                503,
                "Sign-in unavailable",
                "<p>Sign-in is temporarily unavailable. Please try again later.</p>",
            )
            return

        self._send_redirect(
            {
                "Location": dashboard_path,
                "Set-Cookie": self._session_cookie(token, expires_at),
            }
        )

    def _handle_signup(self, form_data: dict[str, str]) -> None:
        full_name = form_data.get("full_name", "").strip()
        contact_number = form_data.get("contact_number", "").strip()
        email = form_data.get("email", "").strip()
        password = form_data.get("password", "")
        confirm_password = form_data.get("confirm_password", "")

        values = {
            "full_name": full_name,
            "contact_number": contact_number,
            "email": email,
        }
        errors: dict[str, str] = {}
        if not full_name:
            errors["full_name"] = "Enter your full name."
        elif len(full_name) < 2:
            errors["full_name"] = "Enter at least 2 characters."
        elif len(full_name) > 200:
            errors["full_name"] = "Use 200 characters or fewer."
        if len(contact_number) > 40:
            errors["contact_number"] = "Use 40 characters or fewer."
        if not email:
            errors["email"] = "Enter your email address."
        elif len(email) > 254:
            errors["email"] = "Use 254 characters or fewer."
        if not password:
            errors["password"] = "Create a password."
        elif len(password) < 8:
            errors["password"] = "Use at least 8 characters."
        elif len(password) > 1024:
            errors["password"] = "Use 1024 characters or fewer."
        if not confirm_password:
            errors["confirm_password"] = "Confirm your password."
        elif password != confirm_password:
            errors["confirm_password"] = "The passwords do not match."
        if errors:
            self._send_response(400, _signup_form(errors=errors, values=values))
            return

        try:
            success, message, _ = database.create_user(
                email=email,
                full_name=full_name,
                password=password,
                contact_number=contact_number,
                role="citizen",
            )
        except sqlite3.Error:
            self._send_page(
                503,
                "Registration unavailable",
                "<p>Account registration is temporarily unavailable.</p>",
            )
            return

        if not success:
            field_errors = {
                "Please enter a valid email address.": (
                    "email",
                    "Enter a valid email address.",
                ),
                "An account with this email already exists.": (
                    "email",
                    "An account with this email already exists.",
                ),
                "Full name must be at least 2 characters long.": (
                    "full_name",
                    "Enter at least 2 characters.",
                ),
            }
            mapped_error = field_errors.get(message)
            if mapped_error:
                errors[mapped_error[0]] = mapped_error[1]
                self._send_response(
                    400,
                    _signup_form(errors=errors, values=values),
                )
            else:
                self._send_response(
                    400,
                    _signup_form("Account registration could not be completed.", True, values=values),
                )
            return

        self._send_redirect({"Location": "/auth/login?registered=1"})

    def _handle_logout(self) -> None:
        token = self._cookie_token()
        try:
            auth_sessions.revoke_session(token)
        except sqlite3.Error:
            self._send_page(
                503,
                "Sign-out unavailable",
                "<p>Your session could not be invalidated. Please retry.</p>",
            )
            return
        self._send_redirect(
            {
                "Set-Cookie": self._clear_session_cookie(),
            }
        )


class AuthGatewayServer(ThreadingHTTPServer):
    """Threaded local HTTP server for authentication routes."""

    daemon_threads = True
    allow_reuse_address = True


def main() -> None:
    """Starts the gateway on its loopback interface."""
    auth_sessions.session_ttl_seconds()
    auth_sessions.cookie_secure_enabled()
    host = os.environ.get("FIR_AUTH_GATEWAY_HOST", "127.0.0.1")
    port = int(os.environ.get("FIR_AUTH_GATEWAY_PORT", "8502"))
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError(
            "The authentication gateway must bind to a loopback address."
        )
    server = AuthGatewayServer((host, port), AuthGatewayHandler)
    print(f"Authentication gateway listening on {host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
