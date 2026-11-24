"""Orchestration of directory-structure synchronization across union upstreams.

rclone's union backend merges upstreams but does not keep their directory trees
in sync. This module computes the desired set of directories and applies
mkdir/purge/rmdir to each upstream so that creates/deletes propagate.

Two modes are supported:

* ``build_plan``: the original set-based planner (union of the current
  *current* trees). Kept for backwards compatibility.
* ``build_mirror_plan``: a 3-way planner that uses a previously synchronized
  tree (the "baseline") to distinguish creations from deletions and to propagate
  both directions. This is what makes synchronization automatic and bidirectional.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import shlex
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from ..i18n import _
from .rclone import config_dump, list_dirs, mkdir, purge, rmdir, update_remote


@dataclass
class SyncPlan:
    upstreams: list[str]
    to_create: list[tuple[str, str]] = field(default_factory=list)  # (upstream, relpath)
    to_delete: list[tuple[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    baseline: set[str] | None = None  # desired common tree after a successful apply
    deleted_count: int = 0


def parse_upstreams(raw: str) -> list[str]:
    """Parse rclone union 'upstreams' string into a list of upstream specs."""
    if not raw:
        return []
    try:
        parts = shlex.split(raw)
    except ValueError:
        parts = raw.split()
    return [p for p in parts if p.strip()]


def _remote_of(spec: str) -> str:
    if ":" in spec:
        return spec.split(":", 1)[0]
    return spec


def _path_of(spec: str) -> str:
    if ":" in spec:
        return spec.split(":", 1)[1].strip()
    return ""


def _join(base: str, rel: str) -> str:
    # Preserve a leading slash so absolute remote paths (e.g. local:/tmp/...)
    # are not turned into relative ones.
    base = base.rstrip("/")
    if not base:
        return rel
    return f"{base}/{rel}"


def _collapse(path: str, depth: int | None) -> str:
    segs = [s for s in path.split("/") if s]
    if depth and depth > 0:
        segs = segs[:depth]
    return "/".join(segs)


async def build_plan(
    config: Path,
    upstreams: Iterable[str],
    *,
    depth: int = 1,  # 1 = top-level only
    recursive: bool = False,
) -> SyncPlan:
    """Original set-based planner (kept for backwards compatibility)."""
    ups = list(upstreams)
    plan = SyncPlan(upstreams=ups)

    per: dict[str, set[str]] = {}
    for u in ups:
        try:
            dirs = await list_dirs(config, _remote_of(u), _path_of(u), recursive=recursive)
        except Exception as exc:
            plan.errors.append(_("list {u}: {exc}").format(u=u, exc=exc))
            per[u] = set()
            continue
        paths = {d.get("Path", "") for d in dirs if d.get("Path")}

        def collapse(p: str) -> str:
            return _collapse(p, depth)

        paths = {collapse(p) for p in paths if p}
        per[u] = paths

    if not per:
        return plan
    sets = [per[u] for u in ups]
    desired = set().union(*sets)

    for u in ups:
        for p in sorted(desired - per[u]):
            plan.to_create.append((u, p))
        for p in sorted(per[u] - desired):
            plan.to_delete.append((u, p))
    plan.baseline = desired if not plan.errors else None
    return plan


async def build_mirror_plan(
    config: Path,
    upstreams: Iterable[str],
    *,
    baseline: set[str] | None = None,
    previous_upstreams: Iterable[str] | None = None,
    depth: int | None = None,  # None/0 = full recursive
    max_deletions: int = 100,
    allow_delete: bool = True,
) -> SyncPlan:
    """Bidirectional planner using a baseline to propagate creates and deletes.

    ``baseline`` is the set of directories that were known to be synchronized in
    the previous successful run.  When it is ``None`` (first run or upstream set
    changed) only missing directories are created and nothing is deleted.
    """
    ups = list(upstreams)
    plan = SyncPlan(upstreams=ups)

    # Reset baseline if the upstream set changed.
    if previous_upstreams is not None and set(previous_upstreams) != set(ups):
        baseline = None

    per: dict[str, set[str]] = {}
    had_error = False

    async def _list_one(u: str) -> tuple[str, set[str] | None, Exception | None]:
        try:
            dirs = await list_dirs(config, _remote_of(u), _path_of(u), recursive=True)
        except Exception as exc:
            return u, None, exc
        paths = {_collapse(d.get("Path", ""), depth) for d in dirs if d.get("Path")}
        paths.discard("")
        return u, paths, None

    results = await asyncio.gather(*[_list_one(u) for u in ups], return_exceptions=False)
    for u, paths, exc in results:
        if exc is not None:
            plan.errors.append(_("list {u}: {exc}").format(u=u, exc=exc))
            per[u] = set()
            had_error = True
        else:
            per[u] = paths or set()

    if not ups:
        return plan

    union_current: set[str] = set().union(*per.values()) if per else set()
    all_sets = [per[u] for u in ups]

    # Intersection of the (successfully listed) upstreams.
    if had_error:
        # Treat failed upstreams as "unknown" -> disable deletes.
        intersection_current: set[str] = set()
        allow_delete = False
    else:
        intersection_current = set.intersection(*all_sets) if all_sets else set()

    if baseline is None:
        # First run / reset: only propagate creations.
        new_paths = union_current
        deleted_paths: set[str] = set()
    else:
        new_paths = union_current - baseline
        if allow_delete:
            deleted_paths = {p for p in baseline if p not in intersection_current}
        else:
            deleted_paths = set()

    deletes_skipped = False
    # Safety: too many deletions -> skip them this cycle.
    # Count actual per-upstream deletions (a deleted path is removed from every
    # upstream that still has it), not just unique paths.
    delete_estimate = sum(sum(1 for u in ups if p in per.get(u, set())) for p in deleted_paths)
    if allow_delete and delete_estimate > max_deletions:
        plan.errors.append(
            _("demasiados borrados ({n} > {m}); borrados omitidos por seguridad").format(
                n=delete_estimate, m=max_deletions
            )
        )
        deleted_paths = set()
        allow_delete = False
        deletes_skipped = True

    if baseline is None:
        final_common = new_paths
    elif allow_delete:
        final_common = (baseline & intersection_current) | new_paths
        final_common -= deleted_paths
    else:
        # Deletions are not propagated: keep anything still present somewhere.
        final_common = (baseline & union_current) | new_paths

    # Build per-upstream operations.
    for u in ups:
        for p in sorted(final_common - per[u]):
            plan.to_create.append((u, p))
        if allow_delete:
            for p in sorted(per[u] - final_common):
                plan.to_delete.append((u, p))

    plan.deleted_count = len(deleted_paths)
    plan.baseline = final_common if not plan.errors else None
    # If deletes were skipped due to safety, do not advance baseline.
    if deletes_skipped:
        plan.baseline = None
    return plan


async def apply_plan(
    config: Path,
    plan: SyncPlan,
    *,
    concurrency: int = 4,
    delete: bool = False,
    use_purge: bool = False,
) -> list[str]:
    sem = asyncio.Semaphore(concurrency)
    errors: list[str] = []

    # Create parents before children.
    creates = sorted(plan.to_create, key=lambda x: (x[1].count("/"), x[1]))
    # Delete children before parents (deepest first).
    deletes = sorted(plan.to_delete, key=lambda x: x[1].count("/"), reverse=True)

    async def do_create(u: str, p: str) -> None:
        async with sem:
            try:
                await mkdir(config, _remote_of(u), _join(_path_of(u), p))
            except Exception as exc:
                low = str(exc).lower()
                # Some backends report an error when the directory already exists;
                # that is not a real failure for our create-only sync.
                if "exist" in low:
                    return
                errors.append(_("mkdir {u}:{p}: {exc}").format(u=u, p=p, exc=exc))

    async def do_delete(u: str, p: str) -> None:
        async with sem:
            try:
                if use_purge:
                    await purge(config, _remote_of(u), _join(_path_of(u), p))
                else:
                    try:
                        await rmdir(config, _remote_of(u), _join(_path_of(u), p))
                    except Exception as exc:
                        low = str(exc).lower()
                        if "not empty" in low or "directory not empty" in low:
                            await purge(config, _remote_of(u), _join(_path_of(u), p))
                        else:
                            raise
            except Exception as exc:
                errors.append(_("delete {u}:{p}: {exc}").format(u=u, p=p, exc=exc))

    # Process in bounded batches to limit memory pressure on huge trees.
    batch = max(concurrency * 4, 32)

    async def _run_batch(items, fn):
        for i in range(0, len(items), batch):
            chunk = items[i : i + batch]
            await asyncio.gather(*[fn(u, p) for u, p in chunk])

    await _run_batch(creates, do_create)
    if delete:
        await _run_batch(deletes, do_delete)
    return errors


def _parse_cache_time(value: object) -> int:
    if isinstance(value, int):
        return value
    raw = str(value).strip().lower()
    try:
        return int(raw)
    except ValueError:
        pass
    total = 0
    for num, unit in re.findall(r"(\d+)\s*([smh])", raw):
        n = int(num)
        if unit == "s":
            total += n
        elif unit == "m":
            total += n * 60
        elif unit == "h":
            total += n * 3600
    return total if total > 0 else 300


async def normalize_union_cache_times(config, config_password=None) -> None:
    """Repair unions whose ``cache_time`` is stored as a non-integer (e.g. '5m')."""
    try:
        dump = await config_dump(config, config_password=config_password)
    except Exception:
        return
    if not isinstance(dump, dict):
        return
    for name, data in list(dump.items()):
        if not (isinstance(data, dict) and data.get("type") == "union"):
            continue
        ct = data.get("cache_time", None)
        if isinstance(ct, int):
            continue
        seconds = _parse_cache_time(ct)
        with contextlib.suppress(Exception):
            await update_remote(config, name, {"cache_time": seconds})
