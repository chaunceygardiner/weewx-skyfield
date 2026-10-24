"""Shared by the test modules: a check open_url takes, and
a real local server for driving a fetch worker end to end."""
import http.server
import threading
import urllib.error
import urllib.request

import pytest


def _assert_redirect_refused(open_url):
    """open_url, asked for a URL a real local server answers 301, raises
    the 301 and never asks for where it points."""
    hits = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            if self.path == '/old':
                self.send_response(301)
                self.send_header('Location', '/new')
                self.send_header('Content-Length', '0')
                self.end_headers()
            else:
                body = b'redirected to'
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = 'http://127.0.0.1:%d/old' % server.server_address[1]
        with pytest.raises(urllib.error.HTTPError) as caught:
            open_url(urllib.request.Request(url), 5)
        assert caught.value.code == 301
        assert hits == ['/old']
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def assert_redirect_refused():
    return _assert_redirect_refused


class _AnsweringServer:
    """A real HTTP server on this machine answering each GET with the next
    queued (status, body) -- or (status, body, declared_length), to send a
    Content-Length the body does not fill, which the client reads as an
    IncompleteRead; every path asked for is recorded in hits."""

    def __init__(self):
        self.answers = []
        self.hits = []
        answers, hits = self.answers, self.hits

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                status, body, *declared = answers.pop(0)
                self.send_response(status)
                self.send_header('Content-Length', str(declared[0] if declared else len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        self.url = 'http://127.0.0.1:%d/CometEls.txt' % self.server.server_address[1]
        # shutdown() waits out serve_forever's poll, half a second by default
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': 0.02}, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def answering_server():
    server = _AnsweringServer()
    try:
        yield server
    finally:
        server.close()
