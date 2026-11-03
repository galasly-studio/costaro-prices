"""Offline tests for guarded COSTARO labor-source retries."""

import socket
from pathlib import Path
import ssl
import sys
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from labor_network_retry import (
    RETRY_DELAY_SECONDS,
    is_transient_transport_error,
    open_with_guarded_retry,
)
from check_labor_source_health import fetch_html_prefix
from collect_live_labor_quotes import download_html


URL = "https://construct.md/ru/pages/price/"


class FakeResponse:
    headers = {"Content-Type": "text/html"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self):
        return URL

    def read(self, size):
        return b"<html><table></table></html>"


class FakeOpener:
    def __init__(self, failures=()):
        self.failures = list(failures)
        self.calls = 0

    def open(self, request, timeout):
        self.calls += 1

        if self.failures:
            raise self.failures.pop(0)

        return FakeResponse()


def http_error(code):
    return urllib.error.HTTPError(
        URL, code, "Test response", None, None
    )


class GuardedRetryTests(unittest.TestCase):

    def test_timeout_receives_only_one_retry(self):
        opener = FakeOpener([socket.timeout("temporary")])
        pauses = []

        response = open_with_guarded_retry(
            opener, object(), timeout=15, pause=pauses.append
        )

        self.assertIsInstance(response, FakeResponse)
        self.assertEqual(opener.calls, 2)
        self.assertEqual(pauses, [RETRY_DELAY_SECONDS])

    def test_503_receives_one_retry(self):
        opener = FakeOpener([http_error(503)])
        pauses = []

        open_with_guarded_retry(
            opener, object(), timeout=15, pause=pauses.append
        )

        self.assertEqual(opener.calls, 2)
        self.assertEqual(len(pauses), 1)

    def test_only_selected_server_errors_are_transient(self):
        for code in (502, 503, 504):
            self.assertTrue(
                is_transient_transport_error(http_error(code))
            )

        for code in (400, 401, 403, 404, 429, 500):
            self.assertFalse(
                is_transient_transport_error(http_error(code))
            )

    def test_403_and_429_never_retry(self):
        for code in (403, 429):
            with self.subTest(code=code):
                opener = FakeOpener([http_error(code)])
                pauses = []

                with self.assertRaises(urllib.error.HTTPError):
                    open_with_guarded_retry(
                        opener,
                        object(),
                        timeout=15,
                        pause=pauses.append,
                    )

                self.assertEqual(opener.calls, 1)
                self.assertEqual(pauses, [])

    def test_persistent_timeout_is_bounded_to_two_attempts(self):
        opener = FakeOpener([
            socket.timeout("first"),
            socket.timeout("second"),
        ])

        pauses = []

        with self.assertRaises(socket.timeout):
            open_with_guarded_retry(
                opener,
                object(),
                timeout=15,
                pause=pauses.append,
            )

        self.assertEqual(opener.calls, 2)
        self.assertEqual(pauses, [RETRY_DELAY_SECONDS])

    def test_dns_and_tls_failures_never_retry(self):
        failures = [
            urllib.error.URLError(socket.gaierror("dns")),
            urllib.error.URLError(ssl.SSLError("tls")),
        ]

        for failure in failures:
            with self.subTest(failure=str(failure)):
                opener = FakeOpener([failure])
                pauses = []

                with self.assertRaises(urllib.error.URLError):
                    open_with_guarded_retry(
                        opener,
                        object(),
                        timeout=15,
                        pause=pauses.append,
                    )

                self.assertEqual(opener.calls, 1)
                self.assertEqual(pauses, [])

    def test_unapproved_redirect_never_retries(self):
        opener = FakeOpener([
            ValueError("unapproved_redirect"),
        ])

        pauses = []

        with self.assertRaisesRegex(ValueError, "unapproved_redirect"):
            open_with_guarded_retry(
                opener,
                object(),
                timeout=15,
                pause=pauses.append,
            )

        self.assertEqual(opener.calls, 1)
        self.assertEqual(pauses, [])

    def test_invalid_timeout_never_opens_network(self):
        opener = FakeOpener()

        with self.assertRaisesRegex(ValueError, "invalid_request_timeout"):
            open_with_guarded_retry(
                opener,
                object(),
                timeout=0,
                pause=lambda _: None,
            )

        self.assertEqual(opener.calls, 0)

    def test_live_quote_downloader_uses_guarded_retry(self):
        opener = FakeOpener([socket.timeout("temporary")])

        with patch(
            "collect_live_labor_quotes.urllib.request.build_opener",
            return_value=opener,
        ), patch(
            "labor_network_retry.time.sleep",
            return_value=None,
        ):
            html = download_html(URL)

        self.assertIn("<table>", html)
        self.assertEqual(opener.calls, 2)

    def test_source_health_downloader_uses_guarded_retry(self):
        opener = FakeOpener([http_error(503)])

        with patch(
            "check_labor_source_health.urllib.request.build_opener",
            return_value=opener,
        ), patch(
            "labor_network_retry.time.sleep",
            return_value=None,
        ):
            html = fetch_html_prefix(URL)

        self.assertIn("<table>", html)
        self.assertEqual(opener.calls, 2)

    def test_unsafe_source_url_is_rejected_before_open(self):
        opener = FakeOpener()

        with patch(
            "collect_live_labor_quotes.urllib.request.build_opener",
            return_value=opener,
        ):
            with self.assertRaises(ValueError):
                download_html("https://example.com/private")

        self.assertEqual(opener.calls, 0)


if __name__ == "__main__":
    unittest.main()