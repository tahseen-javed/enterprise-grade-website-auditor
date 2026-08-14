"""
The packaged app is a single process: the backend serves the built frontend
(frontend/dist) directly, so end users only ever run one program on one
port. These tests are written to be honest regardless of whether the
frontend has been built in the environment running the suite (it may not
have been, e.g. in a fresh clone before `setup.bat`/`npm run build` has run) -
they assert whichever behaviour is actually correct for that state, rather
than assuming the build exists.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import FRONTEND_DIST, app


class TestFrontendServing:
    def test_root_serves_the_built_app_or_a_helpful_pointer(self):
        with TestClient(app) as client:
            r = client.get("/")
        assert r.status_code == 200
        if FRONTEND_DIST.is_dir():
            assert "text/html" in r.headers["content-type"]
            assert "<div id=\"root\"" in r.text or "<div id='root'" in r.text
        else:
            body = r.json()
            assert body["app"]
            assert "dist" in body["note"]

    def test_api_routes_are_never_shadowed_by_the_spa_fallback(self):
        with TestClient(app) as client:
            r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_unknown_api_path_is_a_real_404_not_the_spa_shell(self):
        with TestClient(app) as client:
            r = client.get("/api/this-does-not-exist")
        assert r.status_code == 404

    def test_a_client_side_route_falls_back_to_index_html_when_built(self):
        if not FRONTEND_DIST.is_dir():
            return  # nothing to assert without a build; covered by the root test above
        with TestClient(app) as client:
            r = client.get("/leads")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_path_traversal_outside_dist_is_rejected(self):
        if not FRONTEND_DIST.is_dir():
            return
        with TestClient(app) as client:
            r = client.get("/../../../../windows/win.ini")
        # Either normalised away by the HTTP layer or served the SPA shell -
        # never a file from outside frontend/dist.
        assert r.status_code in (200, 404)
        if r.status_code == 200:
            assert "text/html" in r.headers["content-type"]
