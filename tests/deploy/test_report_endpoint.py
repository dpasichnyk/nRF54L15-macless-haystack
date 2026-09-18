import base64
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "/app/endpoint")
import mh_endpoint as endpoint
from report_fetch import MAX_RESPONSE_BYTES, ReportCache

KEYS = [base64.b64encode(bytes([i]) * 32).decode() for i in range(2)]
payload = base64.b64encode((int(time.time()) - 978307200).to_bytes(4, "big") + b"test").decode()
REPORTS = [{"id": key, "payload": payload} for key in KEYS]
GOOD = json.dumps({"statusCode": 200, "results": REPORTS}).encode()


class AppleFixture(BaseHTTPRequestHandler):
    replies = deque()
    searches = []

    def do_POST(self):
        self.searches.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        status, body = self.replies.popleft()
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def log_message(self, *_args):
        return


class ReportEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        auth = Path(cls.directory.name) / "auth.json"
        _ = auth.write_text("{}")
        endpoint.mh_config.getConfigFile = lambda: str(auth)
        endpoint.getAuth = lambda **_kwargs: ("fixture", "fixture")
        endpoint.pypush_gsa_icloud.generate_anisette_headers = lambda: {}
        endpoint.mh_config.getEndpointUser = lambda: ""
        endpoint.mh_config.getEndpointPass = lambda: ""
        cls.apple = HTTPServer(("127.0.0.1", 0), AppleFixture)
        endpoint.FETCH_URL = f"http://127.0.0.1:{cls.apple.server_port}/"
        cls.server = HTTPServer(("127.0.0.1", 0), endpoint.ServerHandler)
        cls.threads = [threading.Thread(target=s.serve_forever) for s in (cls.apple, cls.server)]
        for thread in cls.threads:
            thread.start()

    @classmethod
    def tearDownClass(cls):
        for server in (cls.server, cls.apple):
            server.shutdown()
            server.server_close()
        for thread in cls.threads:
            thread.join()
        cls.directory.cleanup()

    def setUp(self):
        endpoint.report_cache = ReportCache()
        AppleFixture.replies.clear()
        AppleFixture.searches.clear()

    def request(self, data=None):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_port}/",
            data=json.dumps(data if data is not None else {"ids": KEYS}).encode(),
            headers={"Content-Type": "application/json", "Origin": "https://dchristl.github.io"},
        )
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")
            self.assertIsNotNone(response.headers["Content-Length"])
            return response.status, json.load(response)

    def test_separate_search_entries_same_second_reports_and_cache(self):
        AppleFixture.replies.append((200, GOOD))
        status, body = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(len(body["results"]), 2)
        self.assertEqual(AppleFixture.searches, [{
            "search": [{"startDate": 1, "ids": [key]} for key in sorted(KEYS)],
        }])
        self.assertEqual(self.request({"ids": KEYS[::-1], "days": 1})[0], 200)
        self.assertEqual(len(AppleFixture.searches), 1)

    def test_invalid_client_request_never_reaches_apple(self):
        self.assertEqual(self.request({"ids": ["invalid"]})[0], 400)
        self.assertEqual(AppleFixture.searches, [])

    def test_empty_response_and_server_failure_retry_once(self):
        for first in ((200, b""), (503, b"")):
            with self.subTest(first=first):
                self.setUp()
                AppleFixture.replies.extend((first, (200, GOOD)))
                self.assertEqual(self.request()[0], 200)
                self.assertEqual(len(AppleFixture.searches), 2)

    def test_auth_and_rate_limit_failures_are_not_retried_or_cached(self):
        for upstream, expected in ((401, 502), (403, 502), (429, 503)):
            with self.subTest(upstream=upstream):
                self.setUp()
                AppleFixture.replies.extend(((upstream, b""), (200, GOOD)))
                self.assertEqual(self.request()[0], expected)
                self.assertEqual(len(AppleFixture.searches), 1)
                self.assertEqual(self.request()[0], 200)

    def test_repeated_empty_response_is_unavailable_not_cached(self):
        AppleFixture.replies.extend(((200, b""), (200, b""), (200, GOOD)))
        self.assertEqual(self.request()[0], 503)
        self.assertEqual(len(AppleFixture.searches), 2)
        self.assertEqual(self.request()[0], 200)

    def test_bad_or_oversized_response_is_not_cached(self):
        for raw in (b"{", b"x" * (MAX_RESPONSE_BYTES + 1)):
            with self.subTest(size=len(raw)):
                self.setUp()
                AppleFixture.replies.extend(((200, raw), (200, GOOD)))
                self.assertEqual(self.request()[0], 502)
                self.assertEqual(self.request()[0], 200)

    def test_timeout_has_bounded_retry_and_explicit_response(self):
        with patch.object(endpoint.requests, "post", side_effect=endpoint.requests.exceptions.Timeout) as post:
            self.assertEqual(self.request()[0], 504)
            self.assertEqual(post.call_count, 2)


if __name__ == "__main__":
    unittest.main()
