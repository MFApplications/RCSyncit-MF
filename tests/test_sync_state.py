
from rcsyncitmf.services import sync_state


def _setup(monkeypatch, tmp_path):
    app_dir = tmp_path / "cfg"
    app_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("rcsyncitmf.config.APP_DIR", app_dir, raising=False)
    monkeypatch.setattr(sync_state, "STATE_FILE", app_dir / "sync_state.toml", raising=False)


def test_save_load_roundtrip(tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path)
    profile = tmp_path / "p.conf"
    profile.write_text("", encoding="utf-8")
    sync_state.save_state(profile, "union", ["r1:", "r2:"], {"a", "b"})
    st = sync_state.load_state(profile, "union")
    assert isinstance(st, dict)
    assert st["upstreams"] == ["r1:", "r2:"]
    assert set(st["paths"]) == {"a", "b"}
    assert sync_state.last_sync(profile, "union") is not None


def test_state_isolation_by_profile(tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path)
    p1 = tmp_path / "p1.conf"
    p2 = tmp_path / "p2.conf"
    p1.write_text("", encoding="utf-8")
    p2.write_text("", encoding="utf-8")
    sync_state.save_state(p1, "u", ["r1:"], {"x"})
    sync_state.save_state(p2, "u", ["r2:"], {"y"})
    assert set(sync_state.load_state(p1, "u")["paths"]) == {"x"}
    assert set(sync_state.load_state(p2, "u")["paths"]) == {"y"}


def test_delete_state(tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path)
    profile = tmp_path / "p.conf"
    profile.write_text("", encoding="utf-8")
    sync_state.save_state(profile, "u", ["r1:"], {"a"})
    sync_state.delete_state(profile, "u")
    assert sync_state.load_state(profile, "u") is None
