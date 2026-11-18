from pathlib import Path

from rcsyncitmf.services import mount_manager


def test_default_mountpoint_flatpak(tmp_path, monkeypatch):
    monkeypatch.setattr(mount_manager, "in_flatpak", lambda: True, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    mp = mount_manager.default_mountpoint(Path("/tmp/p.conf"), "remote")
    assert mp == tmp_path / ".local" / "share" / "rcsyncitmf" / "mnt" / "p" / "remote"


def test_list_cached_remotes_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert mount_manager.list_cached_remotes() == []


def test_list_cached_remotes_with_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cache_root = tmp_path / ".cache" / "rclone" / "vfs"
    (cache_root / "alpha").mkdir(parents=True)
    (cache_root / "alpha" / "f").write_text("x")
    (cache_root / "beta").mkdir(parents=True)
    (cache_root / "beta" / "g").write_text("x")
    (cache_root / "notadir.txt").write_text("x")
    (cache_root / "emptydir").mkdir(parents=True)
    assert mount_manager.list_cached_remotes() == ["alpha", "beta"]


def test_has_cache_false(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert mount_manager.has_cache("nope") is False


def test_has_cache_true(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cache_dir = tmp_path / ".cache" / "rclone" / "vfs" / "remote"
    cache_dir.mkdir(parents=True)
    (cache_dir / "file").write_text("x")
    assert mount_manager.has_cache("remote") is True


def test_safe_remote():
    assert mount_manager._safe_remote("a/b c") == "a_b_c"


def test_read_mount_log_missing(tmp_path):
    rec = {"remote": "r", "config": str(tmp_path / "p.conf")}
    # no log file -> fallback message
    text = mount_manager.read_mount_log(rec)
    assert "log" in text.lower() or "generado" in text.lower() or "disponible" in text.lower()


def test_default_mountpoint_custom_dir(tmp_path, monkeypatch):
    custom = tmp_path / "custommnt"
    custom.mkdir()
    monkeypatch.setattr(
        "rcsyncitmf.config.load_settings",
        lambda: {"mounts_dir": str(custom)},
        raising=False,
    )
    mp = mount_manager.default_mountpoint(Path("/tmp/p.conf"), "remote")
    assert mp == custom / "p" / "remote"


def test_cleanup_empty_mount_dirs(tmp_path, monkeypatch):
    base = tmp_path / "mnt"
    (base / "prof" / "remote").mkdir(parents=True)
    # empty nested dir should be removed
    (base / "prof2").mkdir(parents=True)
    # non-empty should remain
    (base / "prof3").mkdir(parents=True)
    (base / "prof3" / "file.txt").write_text("x")
    monkeypatch.setattr(mount_manager, "default_mounts_base", lambda: base, raising=False)
    removed = mount_manager.cleanup_empty_mount_dirs()
    assert removed >= 2
    assert not (base / "prof").exists()
    assert not (base / "prof2").exists()
    assert (base / "prof3").exists()
