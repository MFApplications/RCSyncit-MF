import asyncio
from pathlib import Path

from rcsyncitmf.services import union_sync


def test_parse_upstreams_empty():
    assert union_sync.parse_upstreams("") == []
    assert union_sync.parse_upstreams("   ") == []


def test_parse_upstreams_shlex():
    raw = "remote1:/a remote2:/b"
    assert union_sync.parse_upstreams(raw) == ["remote1:/a", "remote2:/b"]


def test_collapse():
    assert union_sync._collapse("a/b/c", None) == "a/b/c"
    assert union_sync._collapse("a/b/c", 1) == "a"
    assert union_sync._collapse("a/b/c", 2) == "a/b"
    assert union_sync._collapse("", 1) == ""


def test_join():
    assert union_sync._join("base", "rel") == "base/rel"
    assert union_sync._join("base/", "rel") == "base/rel"
    assert union_sync._join("", "rel") == "rel"
    assert union_sync._join("base", "") == "base/"


def test_build_mirror_plan_first_run(monkeypatch):
    async def fake_list_dirs(config, remote, path, recursive=True):
        if remote == "r1":
            return [{"Path": "foo"}, {"Path": "bar/baz"}]
        if remote == "r2":
            return [{"Path": "foo"}]
        return []

    monkeypatch.setattr(union_sync, "list_dirs", fake_list_dirs)

    plan = asyncio.run(
        union_sync.build_mirror_plan(
            Path("/tmp/x.conf"),
            ["r1:", "r2:"],
            baseline=None,
            allow_delete=True,
        )
    )
    # union of current dirs should be created on r2 (bar/baz) and nothing deleted
    assert any("bar/baz" in p for _, p in plan.to_create)
    assert plan.to_delete == []
    assert plan.baseline is not None


def test_build_mirror_plan_upstream_change_resets(monkeypatch):
    async def fake_list_dirs(config, remote, path, recursive=True):
        return [{"Path": "foo"}]

    monkeypatch.setattr(union_sync, "list_dirs", fake_list_dirs)

    plan = asyncio.run(
        union_sync.build_mirror_plan(
            Path("/tmp/x.conf"),
            ["r1:", "r2:"],
            baseline={"foo", "old"},
            previous_upstreams=["r1:", "r3:"],
            allow_delete=True,
        )
    )
    # baseline reset -> no deletes
    assert plan.to_delete == []


def test_apply_plan_empty():
    from rcsyncitmf.services.union_sync import SyncPlan

    plan = SyncPlan(upstreams=["r1:"])
    errs = asyncio.run(
        union_sync.apply_plan(Path("/tmp/x.conf"), plan, concurrency=2, delete=False)
    )
    assert errs == []
