from rcsyncitmf.services import rclone


def test_rclone_bin_cache_invalidation(monkeypatch):
    monkeypatch.setattr(rclone, "in_flatpak", lambda: False, raising=False)
    monkeypatch.setattr(
        "rcsyncitmf.config.load_settings", lambda: {"rclone_bin": "rclone"}, raising=False
    )
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/rclone", raising=False)
    assert rclone.rclone_bin() == "/usr/bin/rclone"
    rclone.invalidate_rclone_bin_cache()
    monkeypatch.setattr("shutil.which", lambda name: "/opt/bin/rclone", raising=False)
    assert rclone.rclone_bin() == "/opt/bin/rclone"
