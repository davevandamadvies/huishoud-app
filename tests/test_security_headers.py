from fastapi.testclient import TestClient

from app.main import app
from app.security import SECURITY_HEADERS

client = TestClient(app)


def test_security_headers_on_pages() -> None:
    response = client.get("/")
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value


def test_security_headers_on_static_files() -> None:
    response = client.get("/static/css/app.css")
    assert response.status_code == 200
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_csp_is_strict() -> None:
    csp = client.get("/healthz").headers["content-security-policy"]
    assert "'unsafe-inline'" not in csp
    assert "'unsafe-eval'" not in csp
    assert "frame-ancestors 'none'" in csp
