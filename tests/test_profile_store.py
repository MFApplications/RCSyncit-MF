from rcsyncitmf.services import profile_store


def _setup(monkeypatch, tmp_path):
    app_dir = tmp_path / "cfg"
    profiles_dir = app_dir / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("rcsyncitmf.config.APP_DIR", app_dir, raising=False)
    monkeypatch.setattr("rcsyncitmf.config.PROFILES_DIR", profiles_dir, raising=False)
    monkeypatch.setattr(profile_store, "PROFILES_DIR", profiles_dir, raising=False)
    if hasattr(profile_store, "APP_DIR"):
        monkeypatch.setattr(profile_store, "APP_DIR", app_dir, raising=False)
    import rcsyncitmf.config as c

    monkeypatch.setattr(c, "APP_DIR", app_dir)
    monkeypatch.setattr(c, "PROFILES_DIR", profiles_dir)


def test_create_and_list(tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path)
    p = profile_store.create_profile("foo")
    assert p.name == "foo.conf"
    assert p in profile_store.list_profiles()


def test_create_duplicate(tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path)
    profile_store.create_profile("foo")
    import pytest

    with pytest.raises(FileExistsError):
        profile_store.create_profile("foo")


def test_delete(tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path)
    p = profile_store.create_profile("bar")
    profile_store.delete_profile(p)
    assert p not in profile_store.list_profiles()


def test_rename(tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path)
    p = profile_store.create_profile("old")
    new = profile_store.rename_profile(p, "new")
    assert new.name == "new.conf"
    assert new.exists()


def test_import_unique(tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path)
    src = tmp_path / "incoming.conf"
    src.write_text("[r]\ntype = local\n", encoding="utf-8")
    dst = profile_store.import_profile_unique(src)
    assert dst.exists()
    # second import renames
    dst2 = profile_store.import_profile_unique(src)
    assert dst2 != dst
    assert dst2.exists()


def test_meta_roundtrip(tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path)
    p = profile_store.create_profile("m")
    profile_store.save_meta(p, {"encrypted": True, "vfs": {"cache_mode": "full"}})
    meta = profile_store.load_meta(p)
    assert meta["encrypted"] is True
    assert meta["vfs"]["cache_mode"] == "full"
