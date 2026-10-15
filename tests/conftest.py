"""Shared by the test modules: a check both copies of open_url take."""
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
