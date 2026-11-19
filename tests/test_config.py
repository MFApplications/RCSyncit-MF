import json

from rcsyncitmf import config


def test_load_toml_migrates_legacy_json(tmp_path, monkeypatch):
    app_dir = tmp_path / "cfg"
    app_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "APP_DIR", app_dir, raising=False)
    legacy = app_dir / "settings.json"
    legacy.write_text(json.dumps({"concurrency": 7}), encoding="utf-8")
    target = app_dir / "settings.toml"
    data = config.load_toml(target, legacy=legacy)
    assert data.get("concurrency") == 7
    assert target.exists()
    assert not legacy.exists()
    assert (app_dir / "settings.json.bak").exists()


def test_load_settings_merges_defaults(tmp_path, monkeypatch):
    app_dir = tmp_path / "cfg"
    app_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "APP_DIR", app_dir, raising=False)
    # point SETTINGS_FILE to tmp by monkeypatching module global
    monkeypatch.setattr(config, "SETTINGS_FILE", app_dir / "settings.toml", raising=False)
    settings = config.load_settings()
    assert settings["concurrency"] == 4
    assert settings["language"] == "auto"
