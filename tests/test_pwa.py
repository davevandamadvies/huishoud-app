import struct
from pathlib import Path

from fastapi.testclient import TestClient

ICONS = Path(__file__).resolve().parent.parent / "app" / "static" / "icons"


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_manifest(anon_client: TestClient) -> None:
    r = anon_client.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/manifest+json")
    data = r.json()
    assert data["display"] == "standalone"
    assert data["start_url"] == "/" and data["scope"] == "/"
    assert data["lang"] == "nl"
    sizes = {i["sizes"] for i in data["icons"]}
    assert {"192x192", "512x512"} <= sizes
    assert any(i.get("purpose") == "maskable" for i in data["icons"])
    for icon in data["icons"]:
        assert anon_client.get(icon["src"]).status_code == 200


def test_icon_files_have_declared_sizes() -> None:
    assert png_size(ICONS / "icon-192.png") == (192, 192)
    assert png_size(ICONS / "icon-512.png") == (512, 512)
    assert png_size(ICONS / "maskable-512.png") == (512, 512)


def test_service_worker(anon_client: TestClient) -> None:
    r = anon_client.get("/sw.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/javascript")
    assert r.headers["service-worker-allowed"] == "/"
    assert r.headers["cache-control"] == "no-cache"
    body = r.text
    for event in ("install", "activate", "fetch", "push", "notificationclick"):
        assert f'addEventListener("{event}"' in body
    # Geen gegevens offline: alleen de offline-pagina en haar bestanden
    assert '"/offline"' in body


def test_offline_page_is_public(anon_client: TestClient) -> None:
    r = anon_client.get("/offline")
    assert r.status_code == 200
    assert "Je bent offline" in r.text
    assert 'aria-label="Hoofdmenu"' not in r.text


def test_pages_link_manifest(client: TestClient) -> None:
    assert 'rel="manifest" href="/manifest.webmanifest"' in client.get("/").text
