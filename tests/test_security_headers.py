from fastapi.testclient import TestClient

from app.main import app
from app.security import SECURITY_HEADERS
from tests.conftest import BASE_URL

client = TestClient(app)


def test_security_headers_on_pages(client: TestClient) -> None:
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


def test_csrf_blocks_post_without_origin(anon_client: TestClient) -> None:
    response = anon_client.post("/auth/logout", headers={"HX-Request": "true"})
    assert response.status_code == 403


def test_csrf_blocks_foreign_origin(anon_client: TestClient) -> None:
    response = anon_client.post(
        "/auth/logout",
        headers={"Origin": "https://evil.example", "HX-Request": "true"},
    )
    assert response.status_code == 403


def test_csrf_requires_htmx_header(anon_client: TestClient) -> None:
    response = anon_client.post("/auth/logout", headers={"Origin": BASE_URL})
    assert response.status_code == 403


def test_csrf_allows_same_origin_htmx(anon_client: TestClient) -> None:
    response = anon_client.post(
        "/auth/logout", headers={"Origin": BASE_URL, "HX-Request": "true"}
    )
    assert response.status_code == 204
