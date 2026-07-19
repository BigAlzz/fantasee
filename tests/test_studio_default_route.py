from pathlib import Path

from fantasee_server.api.generated import STUDIO_DIR, serve_index


def test_default_route_keeps_legacy_ui_without_feature_flag(monkeypatch):
    monkeypatch.delenv("FANTASEE_STUDIO_DEFAULT", raising=False)
    response = serve_index()
    assert Path(response.path).resolve() != (STUDIO_DIR / "index.html").resolve()


def test_default_route_can_switch_to_built_studio(monkeypatch):
    if not (STUDIO_DIR / "index.html").is_file():
        return
    monkeypatch.setenv("FANTASEE_STUDIO_DEFAULT", "true")
    response = serve_index()
    assert Path(response.path).resolve() == (STUDIO_DIR / "index.html").resolve()
