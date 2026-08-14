"""
Test setup.

WAE_DATA_DIR is redirected to a throwaway folder *before* any app module is
imported, because settings.py resolves its paths at import time. That keeps the
real data/app.db, uploads and exports untouched by the test run.
"""

from __future__ import annotations

import os
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="outreach-tests-"))
os.environ["WAE_DATA_DIR"] = str(_TEST_DATA_DIR)

from app.db import init_db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _database():
    init_db()
    yield


@pytest.fixture
def data_dir() -> Path:
    return _TEST_DATA_DIR


# --------------------------------------------------------------------------
# A tiny local website, so crawler/audit tests exercise real HTTP without
# depending on the internet or hitting anyone else's server.
# --------------------------------------------------------------------------

HOMEPAGE_GOOD = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Brightwater Plumbing - Emergency plumbers in Leeds</title>
  <meta name="description" content="Brightwater Plumbing are Gas Safe registered emergency plumbers covering Leeds and surrounding areas, available 24 hours a day.">
  <link rel="canonical" href="http://HOST/">
</head>
<body>
  <header>
    <a href="tel:+441132960001">0113 296 0001</a>
    <a href="/contact">Contact us</a>
    <nav><a href="/services">Services</a><a href="/about">About</a><a href="/book">Book now</a></nav>
  </header>
  <h1>Emergency plumbers in Leeds</h1>
  <h2>Our services</h2>
  <p>We are a fully insured, Gas Safe registered team serving Leeds, Bradford and
     the surrounding areas. We offer boiler repair, leak detection, bathroom
     installation and emergency callouts. Established in 2004, we have completed
     over 4,000 jobs. Areas we serve include Leeds, Bradford and Wakefield.</p>
  <h2>What our customers say</h2>
  <p>Testimonials: "Brilliant service" - Sarah, Leeds. Rated 4.9 from 210 reviews.</p>
  <h2>Get a quote</h2>
  <p>Request a quote or book an appointment online. Opening hours: Mon-Fri 8am-6pm.</p>
  <img src="/van.jpg" alt="Brightwater Plumbing van">
  <footer>
    <p>Brightwater Plumbing, 14 Kirkstall Road, Leeds, LS1 4AB.
       Email us at <a href="mailto:info@brightwaterplumbing.co.uk">info@brightwaterplumbing.co.uk</a></p>
    <a href="https://www.facebook.com/brightwaterplumbing">Facebook</a>
  </footer>
</body>
</html>
"""

HOMEPAGE_POOR = """<!doctype html>
<html>
<head><title>Home</title></head>
<body>
  <div style="width:1200px">
    <h1>Home</h1>
    <p>Welcome to our website.</p>
    <a href="/page2">More</a>
    <button>Submit</button>
  </div>
</body>
</html>
"""

CONTACT_PAGE = """<!doctype html>
<html lang="en">
<head><meta name="viewport" content="width=device-width, initial-scale=1"><title>Contact Brightwater Plumbing</title></head>
<body>
  <h1>Contact us</h1>
  <p>Call <a href="tel:+441132960001">0113 296 0001</a> or email
     <a href="mailto:bookings@brightwaterplumbing.co.uk">bookings@brightwaterplumbing.co.uk</a>.</p>
  <p>You can also reach the office at office [at] brightwaterplumbing [dot] co [dot] uk.</p>
  <p>Find us at 14 Kirkstall Road, Leeds, LS1 4AB. Opening hours Mon-Fri 8am-6pm.</p>
  <form action="/send" method="post">
    <input type="text" name="name" placeholder="Your name">
    <input type="email" name="email" placeholder="Your email">
    <input type="tel" name="phone" placeholder="Phone">
    <textarea name="message" placeholder="How can we help?"></textarea>
    <button type="submit">Request a callback</button>
  </form>
  <a href="https://wa.me/441132960001">Chat on WhatsApp</a>
</body>
</html>
"""

ABOUT_PAGE = """<!doctype html>
<html lang="en"><head><title>About Brightwater Plumbing</title></head>
<body><h1>About us</h1>
<h2>Dave Wilkinson</h2>
<p>Dave Wilkinson, owner, founded Brightwater Plumbing in 2004. Fully insured and
   Gas Safe registered.</p>
</body></html>
"""


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):  # keep the test output clean
        return

    def _send(self, body: str, status: int = 200, ctype: str = "text/html; charset=utf-8"):
        payload = body.replace("HOST", self.headers.get("Host", "localhost")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_HEAD(self):  # noqa: N802
        if self.path in ("/", "/contact", "/about", "/services", "/robots.txt", "/sitemap.xml"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/":
            self._send(HOMEPAGE_GOOD)
        elif path == "/poor":
            self._send(HOMEPAGE_POOR)
        elif path == "/contact":
            self._send(CONTACT_PAGE)
        elif path == "/about":
            self._send(ABOUT_PAGE)
        elif path == "/services":
            self._send("<html lang='en'><head><title>Services</title></head><body>"
                       "<h1>Our services</h1><p>Boiler repair and leak detection.</p></body></html>")
        elif path == "/robots.txt":
            self._send("User-agent: *\nDisallow: /private\nSitemap: http://%s/sitemap.xml\n"
                       % self.headers.get("Host", "localhost"), ctype="text/plain")
        elif path == "/sitemap.xml":
            self._send('<?xml version="1.0"?><urlset><url><loc>/</loc></url></urlset>',
                       ctype="application/xml")
        elif path == "/private":
            self._send("<html><body>should not be crawled</body></html>")
        elif path == "/broken-link-target":
            self._send("<html><body>gone</body></html>", status=404)
        elif path == "/forbidden":
            self._send("<html><body>no</body></html>", status=403)
        else:
            self._send("<html><body>Not found</body></html>", status=404)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def local_site():
    """Returns the base URL of a small local website used by crawler tests."""
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
async def fetcher():
    from app.core.fetcher import Fetcher

    f = Fetcher(
        user_agent="WebsiteAuditBot/1.0 (test)",
        timeout_s=8.0,
        per_domain_concurrency=2,
        per_domain_delay_ms=0,
        max_retries=0,
        respect_robots=True,
    )
    try:
        yield f
    finally:
        await f.aclose()
