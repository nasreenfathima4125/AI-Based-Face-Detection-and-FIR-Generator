"""HTTP integration tests for the same-origin authentication gateway."""

from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from http.cookies import SimpleCookie
import os
import secrets
import sqlite3
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from test_database_support import isolate_database

import auth_sessions
import database
from auth_gateway import AuthGatewayHandler


class TestAuthenticationGateway(unittest.TestCase):
    def setUp(self):
        self.database_path = isolate_database(self, database)
        self.environment = patch.dict(
            os.environ,
            {
                "FIR_AUTH_ALLOWED_HOSTS": "127.0.0.1",
                "FIR_AUTH_COOKIE_SECURE": "false",
                "FIR_AUTH_TRUST_PROXY": "true",
                "FIR_AUTH_SESSION_TTL_SECONDS": "43200",
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            AuthGatewayHandler,
        )
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.server_thread.start()
        self.addCleanup(self._stop_server)
        self.host, self.port = self.server.server_address
        self.origin = f"http://{self.host}:{self.port}"
        self.host_header = f"{self.host}:{self.port}"

    def _stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=3)

    def _request(
        self,
        method,
        path,
        fields=None,
        headers=None,
    ):
        request_headers = dict(headers or {})
        body = None
        if fields is not None:
            body = urlencode(fields).encode("utf-8")
            request_headers["Content-Type"] = (
                "application/x-www-form-urlencoded"
            )
            request_headers["Content-Length"] = str(len(body))
        connection = HTTPConnection(self.host, self.port, timeout=5)
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        response_body = response.read()
        result = response.status, response.getheaders(), response_body
        connection.close()
        return result

    def _admin_user_id(self):
        with database.get_db_connection() as connection:
            return connection.execute(
                "SELECT id FROM users WHERE role = 'admin' LIMIT 1"
            ).fetchone()[0]

    def _same_origin_headers(self):
        return {
            "Origin": self.origin,
            "Host": self.host_header,
        }

    def test_login_issues_http_only_cookie_and_new_request_resolves_session(self):
        status, _, page = self._request("GET", "/auth/login", headers={"Host": self.host_header})
        self.assertEqual(status, 200)
        self.assertIn(b'name="password"', page)
        self.assertIn(b"Don't have an account?", page)
        self.assertIn(b'href="/auth/signup">Create Account</a>', page)
        login_headers = self._same_origin_headers()
        status, response_headers, _ = self._request(
            "GET",
            "/auth/login",
            headers=login_headers,
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            dict(response_headers)["Referrer-Policy"],
            "same-origin",
        )

        headers = self._same_origin_headers()
        status, response_headers, body = self._request(
            "POST",
            "/auth/login",
            {
                "email": "officer@keralapolice.demo",
                "password": "Police@123",
            },
            headers,
        )
        self.assertEqual(status, 303)
        self.assertEqual(body, b"")
        response_header_map = dict(response_headers)
        cookie = SimpleCookie()
        cookie.load(response_header_map["Set-Cookie"])
        token = cookie[auth_sessions.SESSION_COOKIE_NAME].value
        self.assertTrue(cookie[auth_sessions.SESSION_COOKIE_NAME]["httponly"])
        self.assertEqual(
            cookie[auth_sessions.SESSION_COOKIE_NAME]["samesite"],
            "Lax",
        )
        self.assertEqual(
            cookie[auth_sessions.SESSION_COOKIE_NAME]["path"],
            "/",
        )
        self.assertEqual(
            cookie[auth_sessions.SESSION_COOKIE_NAME]["max-age"],
            "43200",
        )
        self.assertFalse(cookie[auth_sessions.SESSION_COOKIE_NAME]["secure"])
        self.assertEqual(
            response_header_map["Location"],
            "/police_dashboard",
        )
        self.assertNotIn(b"Police@123", body)

        user_after_refresh = auth_sessions.current_user_from_cookies(
            {auth_sessions.SESSION_COOKIE_NAME: token}
        )
        self.assertEqual(user_after_refresh["role"], "police")
        with database.get_db_connection() as connection:
            row = connection.execute(
                "SELECT token_hash FROM auth_sessions"
            ).fetchone()
        self.assertNotEqual(row["token_hash"], token)

    def test_signup_page_shows_form_and_direct_login_link(self):
        status, _, page = self._request(
            "GET",
            "/auth/signup",
            headers={"Host": self.host_header},
        )
        self.assertEqual(status, 200)
        for field in (
            b'name="full_name"',
            b'name="contact_number"',
            b'name="email"',
            b'name="password"',
            b'name="confirm_password"',
        ):
            self.assertIn(field, page)
        self.assertIn(b">Create Account</button>", page)
        self.assertIn(
            b'<a href="/auth/login">Sign In</a>',
            page,
        )

    def test_health_endpoint_reports_only_service_availability(self):
        status, response_headers, body = self._request(
            "GET",
            "/auth/health",
            headers={"Host": self.host_header},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, b"ok")
        self.assertNotIn("Set-Cookie", dict(response_headers))

    def test_login_redirects_each_database_role_to_its_dashboard(self):
        accounts = (
            ("citizen@example.com", "Citizen@123", "citizen"),
            ("officer@keralapolice.demo", "Police@123", "police"),
            ("admin@firsystem.demo", "Admin@123", "admin"),
        )
        for email, password, role in accounts:
            with self.subTest(role=role):
                status, response_headers, _ = self._request(
                    "POST",
                    "/auth/login",
                    {
                        "email": email,
                        "password": password,
                        # The submitted role must not affect the DB role redirect.
                        "role": "admin" if role == "citizen" else "citizen",
                    },
                    self._same_origin_headers(),
                )
                self.assertEqual(status, 303)
                response_header_map = dict(response_headers)
                self.assertEqual(
                    response_header_map["Location"],
                    f"/{role}_dashboard",
                )
                cookie = SimpleCookie()
                cookie.load(response_header_map["Set-Cookie"])
                token = cookie[auth_sessions.SESSION_COOKIE_NAME].value
                self.assertEqual(auth_sessions.resolve_session(token)["role"], role)

    def test_https_forwarded_by_trusted_proxy_sets_secure_cookie(self):
        headers = self._same_origin_headers()
        headers["Origin"] = f"https://{self.host_header}"
        headers["X-Forwarded-Proto"] = "https"
        status, response_headers, _ = self._request(
            "POST",
            "/auth/login",
            {
                "email": "officer@keralapolice.demo",
                "password": "Police@123",
            },
            headers,
        )
        self.assertEqual(status, 303)
        cookie = SimpleCookie()
        cookie.load(dict(response_headers)["Set-Cookie"])
        self.assertTrue(cookie[auth_sessions.SESSION_COOKIE_NAME]["secure"])

    def test_gateway_failure_does_not_expose_internal_errors(self):
        headers = self._same_origin_headers()
        with patch.object(
            database,
            "authenticate_user",
            side_effect=sqlite3.OperationalError("private database detail"),
        ):
            status, response_headers, body = self._request(
                "POST",
                "/auth/login",
                {
                    "email": "officer@keralapolice.demo",
                    "password": "Police@123",
                },
                headers,
            )
        self.assertEqual(status, 503)
        self.assertNotIn(b"private database detail", body)
        self.assertNotIn(b"Police@123", body)
        self.assertNotIn("Set-Cookie", dict(response_headers))

    def test_bad_password_and_cross_origin_post_do_not_create_sessions(self):
        headers = self._same_origin_headers()
        status, response_headers, body = self._request(
            "POST",
            "/auth/login",
            {
                "email": "officer@keralapolice.demo",
                "password": "incorrect-secret-value",
            },
            headers,
        )
        self.assertEqual(status, 401)
        self.assertNotIn(b"incorrect-secret-value", body)
        self.assertNotIn(b"Invalid email or password", body)
        self.assertNotIn("Set-Cookie", dict(response_headers))

        cross_origin_headers = dict(headers)
        cross_origin_headers["Origin"] = "https://attacker.example"
        status, _, body = self._request(
            "POST",
            "/auth/login",
            {
                "email": "officer@keralapolice.demo",
                "password": "Police@123",
            },
            cross_origin_headers,
        )
        self.assertEqual(status, 403)
        self.assertNotIn(b"Police@123", body)
        with database.get_db_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM auth_sessions"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_logout_revokes_session_and_expires_cookie(self):
        success, _, user = database.authenticate_user(
            "officer@keralapolice.demo",
            "Police@123",
        )
        self.assertTrue(success)
        token, _ = auth_sessions.create_session(user["id"])
        logout_headers = self._same_origin_headers()
        logout_headers["Cookie"] = (
            f"{auth_sessions.SESSION_COOKIE_NAME}={token}"
        )
        status, _, page = self._request(
            "GET",
            "/auth/logout",
            headers={"Host": self.host_header},
        )
        self.assertEqual(status, 200)
        self.assertIn(b'method="post"', page)

        status, response_headers, _ = self._request(
            "POST",
            "/auth/logout",
            {},
            logout_headers,
        )
        self.assertEqual(status, 303)
        self.assertEqual(dict(response_headers)["Location"], "/")
        cookie = SimpleCookie()
        cookie.load(dict(response_headers)["Set-Cookie"])
        self.assertEqual(cookie[auth_sessions.SESSION_COOKIE_NAME]["max-age"], "0")
        self.assertTrue(cookie[auth_sessions.SESSION_COOKIE_NAME]["httponly"])
        self.assertIsNone(auth_sessions.resolve_session(token))

    def test_https_logout_clears_cookie_with_secure_flag(self):
        success, _, user = database.authenticate_user(
            "officer@keralapolice.demo",
            "Police@123",
        )
        self.assertTrue(success)
        token, _ = auth_sessions.create_session(user["id"])
        headers = self._same_origin_headers()
        headers["Origin"] = f"https://{self.host_header}"
        headers["X-Forwarded-Proto"] = "https"
        headers["Cookie"] = f"{auth_sessions.SESSION_COOKIE_NAME}={token}"
        status, response_headers, _ = self._request(
            "POST",
            "/auth/logout",
            {},
            headers,
        )
        self.assertEqual(status, 303)
        cookie = SimpleCookie()
        cookie.load(dict(response_headers)["Set-Cookie"])
        cleared_cookie = cookie[auth_sessions.SESSION_COOKIE_NAME]
        self.assertTrue(cleared_cookie["secure"])
        self.assertEqual(cleared_cookie["max-age"], "0")

    def test_signing_in_as_another_user_uses_a_new_identity(self):
        login_headers = self._same_origin_headers()
        status, response_headers, _ = self._request(
            "POST",
            "/auth/login",
            {
                "email": "officer@keralapolice.demo",
                "password": "Police@123",
            },
            login_headers,
        )
        self.assertEqual(status, 303)
        first_cookie = SimpleCookie()
        first_cookie.load(dict(response_headers)["Set-Cookie"])
        first_token = first_cookie[auth_sessions.SESSION_COOKIE_NAME].value

        logout_headers = dict(login_headers)
        logout_headers["Cookie"] = (
            f"{auth_sessions.SESSION_COOKIE_NAME}={first_token}"
        )
        status, _, _ = self._request(
            "POST",
            "/auth/logout",
            {},
            logout_headers,
        )
        self.assertEqual(status, 303)
        self.assertIsNone(auth_sessions.resolve_session(first_token))

        status, response_headers, _ = self._request(
            "POST",
            "/auth/login",
            {
                "email": "citizen@example.com",
                "password": "Citizen@123",
            },
            login_headers,
        )
        self.assertEqual(status, 303)
        second_cookie = SimpleCookie()
        second_cookie.load(dict(response_headers)["Set-Cookie"])
        second_token = second_cookie[auth_sessions.SESSION_COOKIE_NAME].value
        self.assertNotEqual(first_token, second_token)
        self.assertEqual(auth_sessions.resolve_session(second_token)["role"], "citizen")

    def test_signup_creates_citizen_without_issuing_a_session(self):
        status, response_headers, _ = self._request(
            "POST",
            "/auth/signup",
            {
                "full_name": "Fictional Gateway Citizen",
                "contact_number": "9876543210",
                "email": "gateway-citizen@example.test",
                "password": "Citizen@123",
                "confirm_password": "Citizen@123",
            },
            self._same_origin_headers(),
        )
        self.assertEqual(status, 303)
        location = dict(response_headers)["Location"]
        self.assertEqual(location, "/auth/login?registered=1")
        status, _, login_page = self._request(
            "GET",
            location,
            headers={"Host": self.host_header},
        )
        self.assertEqual(status, 200)
        self.assertIn(
            b"Your account has been created. Sign in to continue.",
            login_page,
        )
        self.assertIn(b'name="password"', login_page)
        created = next(
            user
            for user in database.get_all_users(admin_user_id=self._admin_user_id())
            if user["email"] == "gateway-citizen@example.test"
        )
        self.assertEqual(created["role"], "citizen")
        with database.get_db_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM auth_sessions"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_signup_ignores_police_and_admin_privilege_fields(self):
        password = secrets.token_urlsafe(18)
        for requested_role in ("police", "admin"):
            with self.subTest(role=requested_role):
                email = f"privilege-attempt-{requested_role}@example.test"
                status, _, _ = self._request(
                    "POST",
                    "/auth/signup",
                    {
                        "full_name": "Synthetic Signup Citizen",
                        "contact_number": "9876543210",
                        "email": email,
                        "password": password,
                        "confirm_password": password,
                        "role": requested_role,
                        "is_admin": "true",
                        "privilege": requested_role,
                    },
                    self._same_origin_headers(),
                )
                self.assertEqual(status, 303)
                created = next(
                    user
                    for user in database.get_all_users(
                        admin_user_id=self._admin_user_id()
                    )
                    if user["email"] == email
                )
                self.assertEqual(created["role"], "citizen")

    def test_signup_validation_and_duplicate_email_errors_are_field_specific(self):
        status, _, page = self._request(
            "POST",
            "/auth/signup",
            {
                "full_name": "",
                "contact_number": "",
                "email": "new-citizen@example.test",
                "password": "short",
                "confirm_password": "different",
            },
            self._same_origin_headers(),
        )
        self.assertEqual(status, 400)
        self.assertIn(b'id="full_name-error"', page)
        self.assertIn(b'id="password-error"', page)
        self.assertIn(b'id="confirm_password-error"', page)
        self.assertIn(b'aria-invalid="true"', page)
        self.assertNotIn(b"short", page)
        self.assertNotIn(b"different", page)

        status, _, page = self._request(
            "POST",
            "/auth/signup",
            {
                "full_name": "Fictional Duplicate Citizen",
                "contact_number": "9876543210",
                "email": "citizen@example.com",
                "password": "UniquePassword123",
                "confirm_password": "UniquePassword123",
            },
            self._same_origin_headers(),
        )
        self.assertEqual(status, 400)
        self.assertIn(b'id="email-error"', page)
        self.assertIn(b"An account with this email already exists.", page)
        self.assertIn(b'value="citizen@example.com"', page)
        with database.get_db_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM users WHERE email = ?",
                ("citizen@example.com",),
            ).fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
