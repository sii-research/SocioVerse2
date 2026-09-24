"""Shared helper for the SocioVerse2 workflow skills.

Scaffolds a standardized study workspace and provides the strict-contract load/save
helpers (thin wrappers over socioverse.validation) the skills must use at every boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

from socioverse.validation import HandoffError, validate_handoff, write_artifact  # noqa: F401

STUDY_SUBDIRS = ["environment", "environment/sources", "population", "simulation",
                 "trajectory", "trajectory/steps", "reports", "reports/figures",
                 "grounding", "narrative"]
# ``narrative/<stage>.json`` holds each stage's L2 reasoning as a durable file (written by
# dashboard/hooks/sv_emit.py) so it rides version snapshots + branch restores exactly like every
# other artifact — the dashboard reads it from whichever version dir it renders, so archived
# versions show their own reasoning and a carried stage never shows a sibling version's text.


def scaffold(studies_root: str | Path, study_id: str) -> Path:
    """Create the standardized study workspace and return its path."""
    root = Path(studies_root) / study_id
    for sub in STUDY_SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def study_paths(study_dir: str | Path) -> dict[str, Path]:
    d = Path(study_dir)
    return {
        "study": d / "study.yaml",
        "resources": d / "resources.json",
        "environment": d / "environment" / "environment.json",
        "population": d / "population" / "population.json",
        "roster": d / "population" / "roster.jsonl",
        "simulation": d / "simulation" / "simulation.json",
        "duckdb": d / "trajectory" / "study.duckdb",
        "metrics": d / "trajectory" / "metrics_history.json",
        "report": d / "reports" / "report.md",
        "figures": d / "reports" / "figures",
        "grounding": d / "grounding" / "grounding.json",
    }


def write_roster(path: str | Path, rows) -> Path:
    """Write the materialized initial roster (population/roster.jsonl): one JSON line per agent,
    the t=0 panel row (agent_id, step, state, action_kind, action_payload). This is the durable
    'instantiated agents' artifact sv-build-population produces so the dashboard's agent inspector
    can show every initialized agent BEFORE any run — the same shape the live panel_live.jsonl
    uses, so the dashboard reads it with no special casing. ``rows`` = TrajectoryRecords (or dicts
    with those keys). Lives under population/, so version snapshots keep it."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    def _get(r, k, default=None):
        return getattr(r, k, default) if not isinstance(r, dict) else r.get(k, default)

    with p.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({
                "agent_id": _get(r, "agent_id"),
                "step": _get(r, "step", 0),
                "state": _get(r, "state", {}),
                "action_kind": _get(r, "action_kind"),
                "action_payload": _get(r, "action_payload", {}),
            }, ensure_ascii=False) + "\n")
    return p


def save_study_yaml(path: str | Path, study_spec) -> Path:
    """StudySpec is written as JSON-in-.yaml (valid YAML, simple + re-loadable)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(study_spec.model_dump_json(indent=2), encoding="utf-8")
    return p


def load_study_yaml(path: str | Path):
    from socioverse.schemas import StudySpec

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return StudySpec.model_validate(data)


def fork_study(
    studies_root: str | Path,
    source_study_id: str,
    new_study_id: str,
    *,
    status: str = "draft",
) -> Path:
    """Path-A reuse: copy an existing study into a NEW ``study_id`` so the source stays intact.

    SocioVerse2's reuse rule is **never edit a matched or reference study in place — fork it.** Any
    study whose ``study.yaml`` carries ``reference: true`` (the bundled templates), and any
    already-adapted study, is a read-only baseline; a new query becomes its own study. This copies the source's
    authored artifacts (``study.yaml`` + the resources/environment/population/simulation JSON
    that exist, plus ``grounding/grounding.json`` — the fork inherits the source's real-world
    anchors and refreshes only the entries it changes), rewrites the fork's identity
    (``study_id`` across study.yaml AND every copied artifact that embeds it —
    resources/environment/population/simulation — plus ``status`` / ``created_by``), forces
    ``reference: false`` (a working fork is never a read-only template), and
    DROPS stale run outputs (``trajectory/*``, ``reports/*``) so the fork re-runs clean. No code
    is copied or written: the fork's bundles keep pointing at the source's registered
    ``provider_refs`` (that is what makes this the "no new code" path). Returns the new study
    root. Refuses to overwrite an existing ``study_id``.
    """
    src = Path(studies_root) / source_study_id
    if not (src / "study.yaml").exists():
        raise FileNotFoundError(f"no study to fork at {src}")
    dst = Path(studies_root) / new_study_id
    if dst.exists():
        raise FileExistsError(f"refusing to overwrite existing study {dst}")

    scaffold(studies_root, new_study_id)
    src_paths, dst_paths = study_paths(src), study_paths(dst)
    for key in ("study", "resources", "environment", "population", "simulation", "grounding"):
        s = src_paths[key]
        if s.exists():
            dst_paths[key].parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, dst_paths[key])

    spec = load_study_yaml(dst_paths["study"])
    spec.study_id = new_study_id
    spec.status = status
    spec.created_by = f"sv-init (fork of {source_study_id})"
    spec.reference = False   # a working fork is NEVER a read-only template — else it masquerades as
                             # one (blocks in-place edits, shows a REF badge, can be picked as a build template)
    save_study_yaml(dst_paths["study"], spec)

    # Rewrite the copied artifacts' embedded study_id too. resources/environment/population/simulation
    # each carry `study_id`; a stale SOURCE id mis-tags the fork's trajectory store (DuckDB `study_id`),
    # binding the fork's results onto the source study in the dashboard. fork_study historically only
    # rewrote study.yaml, so every caller had to hand-patch these (the recurring fork id-drift bug).
    for key in ("resources", "environment", "population", "simulation"):
        p = dst_paths[key]
        if not p.exists():
            continue
        try:
            obj = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(obj, dict) and obj.get("study_id") not in (None, new_study_id):
            obj["study_id"] = new_study_id
            p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return dst


# ── study versioning (live workspace + frozen snapshots) ───────────────────────
# The study dir is ALWAYS the current version's working copy — python package imports
# (`import studies.<id>` / the chicago adapter) pin the executable code there, so
# versions are not parallel runnable dirs. Creating a new version first freezes the
# whole live state into ``versions/v<N>/`` (a read-only archive the dashboard can
# render), then iterates in place. ``versions.json`` is the manifest: linear ids +
# a ``parent`` field form a tree, so a new version may branch from ANY archived one.

VERSIONS_DIR = "versions"
MANIFEST_NAME = "versions.json"
# Never snapshotted: the snapshot tree itself, the manifest (study-level, live only),
# demo scratch (runs/), caches, and the two transient run files — an archived copy
# must not look mid-run/"live" to the dashboard.
SNAPSHOT_EXCLUDE = {VERSIONS_DIR, MANIFEST_NAME, "runs", "__pycache__", ".DS_Store",
                    "progress.jsonl", "panel_live.jsonl"}
# Kept in the live dir when branching from an older version; everything else is
# replaced so the live dir matches the base snapshot exactly.
RESTORE_KEEP = {VERSIONS_DIR, MANIFEST_NAME, "runs", "__pycache__", ".DS_Store"}
# Run outputs are cleared from the live dir on every version bump (they are preserved
# in the snapshot) so the new version starts honestly at "built, not yet run".
OUTPUT_SUBDIRS = ("trajectory", "reports")


def manifest_path(study_dir: str | Path) -> Path:
    return Path(study_dir) / MANIFEST_NAME


def load_manifest(study_dir: str | Path) -> dict | None:
    p = manifest_path(study_dir)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_manifest(study_dir: str | Path, manifest: dict) -> Path:
    """Atomic write (tmp + rename) — the dashboard poller must never read a torn file."""
    p = manifest_path(study_dir)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
    return p


def current_version(study_dir: str | Path) -> str:
    """The version id the live dir currently carries (implicit ``v1`` pre-manifest)."""
    man = load_manifest(study_dir)
    return (man or {}).get("current") or "v1"


def init_manifest(study_dir: str | Path, note: str = "initial build") -> dict:
    """Register the live dir as ``v1``. sv-init calls this at scaffold/fork time so the
    dashboard shows a default version from day one; pre-versioning studies get it
    lazily on their first /sv-iterate. No-op when a manifest already exists."""
    existing = load_manifest(study_dir)
    if existing:
        return existing
    manifest = {
        "current": "v1",
        "versions": [{"id": "v1", "parent": None, "note": note, "kind": "version",
                      "created_at": time.time(), "snapshot": None, "warm_start": None,
                      "fork_step": None}],
    }
    _write_manifest(study_dir, manifest)
    return manifest


def _snapshot_live(study_dir: Path, version_id: str) -> str:
    """Freeze the live dir into ``versions/<version_id>/``; returns the relative path.

    If the snapshot dir already exists (a previous create_version crashed after
    snapshotting), it is kept as-is: it is the authoritative freeze of that version and
    the live dir may already have moved on — re-copying could overwrite good data.
    """
    rel = f"{VERSIONS_DIR}/{version_id}"
    snap = study_dir / VERSIONS_DIR / version_id
    if not snap.exists():
        shutil.copytree(study_dir, snap,
                        ignore=lambda src, names: [n for n in names if n in SNAPSHOT_EXCLUDE])
    return rel


def version_trajectory_db(study_dir: str | Path, version_id: str) -> Path:
    """Path to an archived version's trajectory store — what warm-start replays from.
    ``create_version`` snapshots the live dir into ``versions/<id>/`` and ``study.duckdb`` is NOT
    in SNAPSHOT_EXCLUDE, so a finished version's panel is preserved here for the next version to
    inherit. (Only defined for versions that have a snapshot; the live/current version's store is
    at ``trajectory/study.duckdb``.)"""
    return Path(study_dir) / VERSIONS_DIR / version_id / "trajectory" / "study.duckdb"


def create_version(study_dir: str | Path, note: str, base: str | None = None,
                   warm_start: dict | None = None, resume_from_stage: str | None = None) -> str:
    """Iterate the study to a NEW version, preserving the current one as a snapshot.

    This is the **version-iterate** path of /sv-iterate (the in-place path simply skips
    this call). Order is crash-safe: (1) freeze live → ``versions/v<current>/``;
    (2) if ``base`` names an older version, restore its snapshot into the live dir
    (``copy2`` keeps mtimes, so untouched artifacts read as carried-from-parent);
    (3) drop the live run outputs (kept in the snapshot) so the new version starts at
    "built, not yet run"; (4) append the new entry + move ``current`` (atomic, last —
    a half-done copy is invisible to the dashboard until the manifest says otherwise).

    Every entry records a ``kind``: a **branch** (``warm_start`` given — inherits the parent's
    realized history by replay and changes only the environment from its fork step on) or a
    **version** (anything else — any artifact may change, the run starts cold). See
    ``create_branch`` / ``check_branch_invariant`` for the branch contract.

    ``note`` is the one-line human description shown in the dashboard's version box.
    ``base`` defaults to the current version; passing an older id starts the new version from
    that archived one instead (cross-version iteration). ``warm_start`` (optional) records the inherit-steps provenance
    on the NEW version entry — ``{"source": <parent v>, "resume_from": K}`` — set by /sv-iterate
    when the user opts to inherit the parent's already-run steps (the parent's snapshot is what
    `sv-run` then replays). ``resume_from_stage`` (optional) records the earliest sv-* stage this
    iteration re-enters (e.g. ``"sv-build-environment"``); the dashboard reads it so the new
    version's progress pointer parks on that stage — rather than reading the parent's carried
    artifacts as this version's finished work — until Claude actually re-authors it. Returns the
    new version id. The caller (skill contract) must not invoke this while a run is writing the
    trajectory store.
    """
    d = Path(study_dir)
    if not (d / "study.yaml").exists():
        raise FileNotFoundError(f"no study at {d}")
    manifest = load_manifest(d) or init_manifest(d)
    cur = manifest["current"]
    entries = {v["id"]: v for v in manifest["versions"]}
    base = base or cur
    if base not in entries:
        raise ValueError(f"unknown base version {base!r}; have {sorted(entries)}")
    # Starting a new VERSION from an older one (base != cur) is a big context switch → default the
    # re-entry to sv-init so the dashboard's review gate (see compute_stages) makes Claude re-review
    # EVERY stage from the start. (A BRANCH is different: create_branch passes sv-build-environment,
    # because E is the only artifact it re-authors.) A same-line new version leaves resume_from_stage
    # to the caller (the earliest affected stage); if that too is omitted, compute_stages fails safe
    # to the first carried stage, never run.
    if resume_from_stage is None and base != cur:
        resume_from_stage = "sv-init"

    # 1) freeze the live dir as the current version's archive
    entries[cur]["snapshot"] = _snapshot_live(d, cur)

    # 2) branching from an older version: make live == that snapshot (minus outputs)
    if base != cur:
        base_snap = d / (entries[base].get("snapshot") or "")
        if not base_snap.is_dir():
            raise FileNotFoundError(f"base version {base!r} has no snapshot at {base_snap}")
        for child in d.iterdir():
            if child.name in RESTORE_KEEP:
                continue
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        for child in base_snap.iterdir():
            if child.name in OUTPUT_SUBDIRS:
                continue  # outputs stay archived; the new version re-runs
            dst = d / child.name
            if child.is_dir():
                shutil.copytree(child, dst)
            else:
                shutil.copy2(child, dst)

    # 3) clear live run outputs (preserved in the snapshot) + restore the empty layout
    for sub in OUTPUT_SUBDIRS:
        if (d / sub).exists():
            shutil.rmtree(d / sub)
    for sub in STUDY_SUBDIRS:
        (d / sub).mkdir(parents=True, exist_ok=True)

    # 4) register the new version and point `current` at it (atomic, last)
    nums = [int(v["id"][1:]) for v in manifest["versions"]
            if v["id"].startswith("v") and v["id"][1:].isdigit()]
    new_id = f"v{(max(nums) if nums else len(manifest['versions'])) + 1}"
    manifest["versions"].append({"id": new_id, "parent": base, "note": note,
                                 # branch = inherits the parent's realized history by replay and
                                 # changes only E from the fork step on; version = anything else.
                                 "kind": "branch" if warm_start else "version",
                                 "created_at": time.time(), "snapshot": None,
                                 "warm_start": warm_start,   # {source, resume_from} | None
                                 "fork_step": _fork_step_of(warm_start),   # first self-computed step | None
                                 "resume_from_stage": resume_from_stage})   # earliest re-entered stage | None
    manifest["current"] = new_id
    _write_manifest(d, manifest)
    return new_id


# ── branch vs version: the two edit domains of the controllable research loop ──────────
# A **branch** is a counterfactual: it inherits its parent's realized history up to a fork
# step (sv-run replays the parent's stored actions — no LLM) and changes ONLY the environment
# from that step on, so everything that differs afterwards is attributable to the declared
# intervention alone. A **version** may change any artifact (population, behaviour function,
# environment, run settings) and starts a cold run; it compares one study design with another.
# Both live in versions.json; ``kind`` says which, and a branch also carries ``fork_step``.

# Artifacts a branch must inherit byte-for-byte from its parent (P and the study's own code).
BRANCH_INVARIANT_FILES = (
    ("population/population.json", "population bundle"),
    ("population/roster.jsonl", "materialized roster"),
)
# simulation.json fields a branch must keep. ``n_steps`` is absent on purpose (a branch may run a
# longer horizon than its parent) and so is ``warm_start`` (that is the branch's own provenance).
BRANCH_INVARIANT_SIM_FIELDS = ("seed", "decision_ref", "decision_args", "collector_ref",
                               "collector_args", "interaction_rounds", "store_ref", "store_args",
                               "engine_args")
# Bundle keys that are rewritten on every author pass and carry no behaviour — never a violation.
_VOLATILE_KEYS = ("created_at", "generated_at", "updated_at", "materialized_at", "written_at")


def _fork_step_of(warm_start: dict | None) -> int | None:
    """The first step a branch computes itself = the parent's last inherited step + 1."""
    if not warm_start or warm_start.get("source") is None:
        return None
    try:
        return int(warm_start.get("resume_from", 0)) + 1
    except (TypeError, ValueError):
        return None


def version_entry(study_dir: str | Path, version_id: str | None = None) -> dict | None:
    """The manifest entry for ``version_id`` (default: the current version)."""
    man = load_manifest(study_dir)
    if not man:
        return None
    vid = version_id or man.get("current") or "v1"
    return next((v for v in man.get("versions", []) if v.get("id") == vid), None)


def version_kind(entry: dict | None) -> str:
    """``"branch"`` or ``"version"``. Manifests written before ``kind`` existed are read by their
    warm-start provenance, so old studies classify correctly without a migration."""
    if not entry:
        return "version"
    kind = entry.get("kind")
    if kind in ("branch", "version"):
        return kind
    return "branch" if (entry.get("warm_start") or {}).get("source") else "version"


def version_fork_step(entry: dict | None) -> int | None:
    """A branch's fork step, derived from warm-start provenance on pre-``fork_step`` manifests."""
    if not entry:
        return None
    fs = entry.get("fork_step")
    if isinstance(fs, int):
        return fs
    return _fork_step_of(entry.get("warm_start"))


def create_branch(study_dir: str | Path, note: str, *, fork_step: int,
                  source: str | None = None,
                  resume_from_stage: str = "sv-build-environment") -> str:
    """Branch the study at ``fork_step`` — the counterfactual path of /sv-iterate.

    The new version inherits ``source``'s realized history for steps ``0..fork_step-1`` (sv-run
    replays that version's stored actions, no LLM, so the inherited steps reproduce the parent
    exactly) and computes ``fork_step`` onward for itself. Only the environment may differ, and
    only from ``fork_step`` on: the intervention is a ScheduledEvent or Broadcast authored at a
    step >= ``fork_step``. ``check_branch_invariant`` enforces that before the run.

    ``source`` defaults to the current version. Naming an older one restores that version's
    artifacts into the live dir first (as ``create_version(base=...)`` does), so the branch really
    departs from that version's design. Re-entry defaults to ``sv-build-environment`` because the
    environment bundle is the only artifact a branch re-authors. Returns the new version id.
    """
    d = Path(study_dir)
    fork_step = int(fork_step)
    if fork_step < 1:
        raise ValueError(f"fork_step must be >= 1 (step 0 is the materialized initial state, "
                         f"nothing to inherit); got {fork_step}")
    src = source or current_version(d)
    return create_version(d, note, base=None if src == current_version(d) else src,
                          warm_start={"source": src, "resume_from": fork_step - 1},
                          resume_from_stage=resume_from_stage)


def _digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _code_digest(root: Path) -> dict[str, str]:
    """(relpath -> sha256) for a study's own python code: ``model.py`` and any adapter module.
    The behaviour function f is code, so a branch that edits it is not a branch."""
    out: dict[str, str] = {}
    for f in sorted(root.glob("*.py")) + sorted(root.glob("adapter/*.py")):
        if "__pycache__" in f.parts:
            continue
        out[str(f.relative_to(root))] = _digest(f) or ""
    return out


def _load_json(path: Path) -> dict | None:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def _stable(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def _strip_volatile(obj: dict | None) -> dict | None:
    return None if obj is None else {k: v for k, v in obj.items() if k not in _VOLATILE_KEYS}


def _env_history(env: dict | None, fork_step: int) -> dict | None:
    """The part of an environment bundle a branch must inherit: the provider and every event or
    broadcast scheduled BEFORE the fork. Layers are compared by the caller (a branch may ADD an
    information layer to carry its broadcast, but never change one the parent already had)."""
    if env is None:
        return None
    def before(items):
        out = []
        for it in items or []:
            try:
                if int(it.get("at_step", 0)) < fork_step:
                    out.append(it)
            except (TypeError, ValueError, AttributeError):
                out.append(it)
        return sorted(out, key=_stable)
    return {"provider_ref": env.get("provider_ref"),
            "provider_args": env.get("provider_args") or {},
            "scheduled_events": before(env.get("scheduled_events")),
            "broadcasts": before((env.get("information_program") or {}).get("broadcasts"))}


def check_branch_invariant(study_dir: str | Path, *, version_id: str | None = None,
                           downgrade: bool = True) -> dict:
    """Verify that the current version really is a branch, and downgrade it to a version if not.

    A branch claims that everything differing from its parent after the fork step is caused by the
    declared intervention. That claim only holds while the population, the study's code, the run
    settings and the pre-fork schedule are the parent's. This compares the live workspace against
    the parent's frozen snapshot and reports every artifact that breaks the claim.

    On a violation the version is **downgraded, not rejected**: ``kind`` becomes ``"version"``,
    the warm-start provenance is dropped (so sv-run does a cold run from step 0 and the results
    stay correct, just more expensive) and the reason is recorded on the entry as
    ``downgraded_from_branch`` for the audit trail. The caller is expected to tell the user.

    Returns ``{kind, ok, violations, downgraded, source, fork_step, error}``. A version (or a
    study with no manifest) is trivially ``ok`` — there is nothing to inherit.
    """
    d = Path(study_dir)
    report = {"kind": "version", "ok": True, "violations": [], "downgraded": False,
              "source": None, "fork_step": None, "error": None}
    man = load_manifest(d)
    if not man:
        return report
    vid = version_id or man.get("current") or "v1"
    entry = next((v for v in man.get("versions", []) if v.get("id") == vid), None)
    if version_kind(entry) != "branch":
        return report

    ws = (entry or {}).get("warm_start") or {}
    source, fork_step = ws.get("source"), version_fork_step(entry)
    report.update(kind="branch", source=source, fork_step=fork_step)
    violations: list[str] = []
    try:
        snap = d / VERSIONS_DIR / str(source)
        if not snap.is_dir():
            violations.append(f"the snapshot of parent version {source} does not exist, so its history cannot be inherited")
        else:
            for rel, label in BRANCH_INVARIANT_FILES:
                live_p, snap_p = d / rel, snap / rel
                if live_p.suffix == ".json":
                    live_v = _strip_volatile(_load_json(live_p)) if live_p.is_file() else None
                    snap_v = _strip_volatile(_load_json(snap_p)) if snap_p.is_file() else None
                    same = _stable(live_v) == _stable(snap_v)
                else:
                    same = _digest(live_p) == _digest(snap_p)
                if not same:
                    violations.append(f"{label} ({rel}) differs from the parent version — a branch must not change the population P")
            if _code_digest(d) != _code_digest(snap):
                violations.append("model code (model.py / adapter/*.py) differs from the parent version "
                                  "— a branch must not change the behavior function f")
            live_sim, snap_sim = _load_json(d / "simulation" / "simulation.json"), \
                _load_json(snap / "simulation" / "simulation.json")
            if live_sim is not None and snap_sim is not None:
                changed = [f for f in BRANCH_INVARIANT_SIM_FIELDS
                           if _stable(live_sim.get(f)) != _stable(snap_sim.get(f))]
                if changed:
                    violations.append("run settings " + ", ".join(changed) +
                                      " differ from the parent version — a branch may only lengthen n_steps")
            live_env, snap_env = _load_json(d / "environment" / "environment.json"), \
                _load_json(snap / "environment" / "environment.json")
            if fork_step is not None and live_env is not None and snap_env is not None:
                if _stable(_env_history(live_env, fork_step)) != \
                        _stable(_env_history(snap_env, fork_step)):
                    violations.append(f"the environment before step {fork_step} (provider / scheduled events / broadcasts) "
                                      "differs from the parent version — a branch may only add interventions at or after the fork step")
                live_layers = {l.get("name"): l for l in (live_env.get("layers") or [])}
                for layer in snap_env.get("layers") or []:
                    name = layer.get("name")
                    if name not in live_layers:
                        violations.append(f"the parent version's environment layer {name!r} was deleted in the branch")
                    elif _stable(live_layers[name]) != _stable(layer):
                        violations.append(f"environment layer {name!r} was rewritten — a branch may only add layers, never change existing ones")
    except Exception as exc:                     # verification must never break a run
        report["error"] = f"{type(exc).__name__}: {exc}"
        return report

    if not violations:
        return report
    report.update(ok=False, violations=violations)
    if downgrade and entry is not None:
        entry["kind"] = "version"
        entry["warm_start"] = None
        entry["fork_step"] = None
        entry["downgraded_from_branch"] = {"source": source, "fork_step": fork_step,
                                           "violations": violations, "at": time.time()}
        _write_manifest(d, man)
        report["downgraded"] = True
        report["kind"] = "version"
    return report


def resolve_warm_start(study_dir: str | Path) -> dict | None:
    """Turn the current version's manifest ``warm_start`` provenance into runnable engine params.

    /sv-iterate records ``{"source": <parent v>, "resume_from": K}`` on the new version entry;
    sv-run calls this to build a ``WarmStartSpec`` — it resolves ``source`` to the parent's
    archived store (``versions/<source>/trajectory/study.duckdb``) and returns
    ``{source_version, source_trajectory, resume_from}``, or ``None`` when there is no warm-start
    or the parent snapshot is missing (→ fall back to a cold run from step 0). Keeps the manifest
    the single source of truth (sv-run doesn't re-derive the resume point)."""
    # The branch contract is verified here, not only in the skill: every path to a run goes
    # through this call. A branch whose workspace no longer satisfies it was downgraded to a
    # plain version by check_branch_invariant, so there is no warm start left to resolve.
    try:
        if not check_branch_invariant(study_dir).get("ok", True):
            return None
    except Exception:
        pass
    man = load_manifest(study_dir)
    if not man:
        return None
    cur = man.get("current")
    entry = next((v for v in man.get("versions", []) if v.get("id") == cur), None)
    ws = (entry or {}).get("warm_start")
    if not ws or not ws.get("source"):
        return None
    db = version_trajectory_db(study_dir, ws["source"])
    if not db.exists():
        return None
    return {"source_version": ws["source"], "source_trajectory": str(db),
            "resume_from": int(ws.get("resume_from", 0))}


def discover_studies(studies_root: str | Path = "studies") -> list:
    """The runtime 'catalog': glob ``studies/*/study.yaml`` -> list[StudySpec].

    sv-init Step 0 calls this to see what has already been adapted, then matches a new
    query against the discovery fields (domain / tags / legacy_simulator / metrics /
    adjustable_params) to choose Path A (reuse) vs Path B (build new). Decentralised by
    design — each study carries its own card in its own study.yaml, so collaborators add
    studies without editing a shared index (no merge conflicts). Malformed/partial
    study.yaml files are skipped rather than raising.
    """
    out = []
    for p in sorted(Path(studies_root).glob("*/study.yaml")):
        try:
            out.append(load_study_yaml(p))
        except Exception:
            continue
    return out


# ── study availability (companion repos and extras a study needs; see StudySpec.requires) ──
# A "sibling:<Name>" requirement resolves exactly like the study seams do: the repo's own
# SV_*_ROOT variable if set (process env, else `.env`), else a clone named <Name> next to this repo. `markers` are the
# paths the seam actually needs inside that checkout. Keep this table in sync with the seams
# (studies/_abm_common/seam.py, studies/consumer_confidence/adapter/engine_seam.py).
_REPO_ROOT = Path(__file__).resolve().parents[1]

SIBLING_REPOS: dict[str, dict] = {
    "SocioVerse-ABM": {
        "env": "SV_ABM_ROOT",
        "markers": ["socioverse_abm", "tasks"],
        "url": "https://github.com/Lishi905/SocioVerse-ABM",
    },
    "ConsumerSim-Consumer-Confidence-Forecast": {
        "env": "SV_CONSUMERSIM_ROOT",
        "markers": ["consumer_pipeline/orchestrator.py"],
        "url": "https://github.com/RunRiotComeOn/ConsumerSim-Consumer-Confidence-Forecast",
    },
}


def sibling_root(name: str) -> Path:
    """Where the companion repo `name` is looked for: $<its env var> (process env, else
    `.env`), else ../<name>."""
    from socioverse.external_events import env_setting

    info = SIBLING_REPOS.get(name) or {}
    env = env_setting(info["env"]) if info.get("env") else None
    return Path(env) if env else _REPO_ROOT.parent / name


def _seam_module(which: str):
    """The study seam that owns a requirement check. The checks live in the seams (the same code
    the studies and the test skip guards run), so the catalog can never disagree with them."""
    import importlib
    import sys

    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    return importlib.import_module({
        "abm": "studies._abm_common.seam",
        "chicago": "studies.chicago_schelling.adapter.engine_seam",
        "workbench": "studies.germany_auto_market.model",
    }[which])


def _extra_missing(name: str) -> list[str] | None:
    """Packages of the `name` extra that a seam imports but that are not importable here;
    None when no seam declares that extra."""
    if name == "abm":
        return _seam_module("abm").abm_missing_deps()
    if name == "chicago":
        return _seam_module("chicago").chicago_missing_deps()
    if name == "workbench":
        return _seam_module("workbench").workbook_missing_deps()
    return None


def requirement_status(req: str) -> dict:
    """Resolve one `requires` entry -> {requirement, ok, where, setup}.

    Supported kinds:
      ``sibling:<Name>``   a companion repo on disk (see SIBLING_REPOS);
      ``extra:<name>``     the Python packages a seam imports, installed by
                           ``pip install -e ".[<name>]"`` (``abm``, ``chicago``,
                           ``workbench``);
      ``legacy:chicago``   the legacy Chicago model's data, located exactly as the chicago
                           seam does ($SV_CHICAGO_LEGACY, $SV_ABM_ROOT, ../SocioVerse-ABM).
    Unknown kinds are reported as not satisfied so a typo never silently marks a study runnable."""
    kind, _, name = req.partition(":")
    if kind == "sibling" and name:
        root = sibling_root(name)
        markers = (SIBLING_REPOS.get(name) or {}).get("markers") or []
        ok = root.is_dir() and all((root / m).exists() for m in markers)
        url = (SIBLING_REPOS.get(name) or {}).get("url")
        setup = (f"git clone {url} ../{name}" if url else f"clone {name} next to this repo")
        env = (SIBLING_REPOS.get(name) or {}).get("env")
        if env:
            setup += f"  (or set {env})"
        return {"requirement": req, "ok": ok, "where": str(root), "setup": setup}
    if kind == "extra" and name:
        try:
            missing = _extra_missing(name)
        except Exception as exc:                      # a broken seam import counts as unmet
            missing = [f"seam import failed: {exc}"]
        if missing is not None:
            return {"requirement": req, "ok": not missing, "where": "",
                    "setup": f'pip install -e ".[{name}]"  (missing: {", ".join(missing)})'}
    if kind == "legacy" and name == "chicago":
        url = SIBLING_REPOS["SocioVerse-ABM"]["url"]
        setup = (f"git clone {url} ../SocioVerse-ABM  (or set SV_CHICAGO_LEGACY to the legacy "
                 "dir, or SV_ABM_ROOT to a SocioVerse-ABM checkout)")
        try:
            seam = _seam_module("chicago")
            root = seam.resolve_chicago_legacy()
            ok, where = seam.chicago_data_present(root), str(root)
        except Exception as exc:                      # a broken seam import counts as unmet
            ok, where = False, f"seam import failed: {exc}"
        return {"requirement": req, "ok": ok, "where": where, "setup": setup}
    return {"requirement": req, "ok": False, "where": "",
            "setup": f"unknown requirement {req!r}"}


def study_availability(spec) -> dict:
    """{requires, available, missing, setup, rerunnable} for one StudySpec."""
    reqs = list(spec.requires or [])
    status = [requirement_status(r) for r in reqs]
    missing = [s["requirement"] for s in status if not s["ok"]]
    return {
        "requires": reqs,
        "available": not missing,
        "missing": missing,
        "setup": [s["setup"] for s in status if not s["ok"]],
        "rerunnable": bool(spec.rerunnable),
    }


def catalog_view(studies_root: str | Path = "studies") -> list[dict]:
    """Compact, matching-relevant projection of discover_studies() for display/routing.

    Besides the discovery fields, every row carries availability: ``requires`` (the
    study.yaml list), ``available`` (every requirement is present on disk), ``missing``
    (the unmet ones), ``setup`` (how to satisfy each missing one) and ``rerunnable``
    (False for imported references). sv-init offers a Path-A fork or a run only when
    ``available and rerunnable``; otherwise it shows the study as "needs <X>" with ``setup``.
    """
    fields = ("study_id", "title", "domain", "tags", "study_type", "metrics",
              "legacy_simulator", "provider_refs", "adjustable_params", "status",
              "demonstrates", "teaches", "reference")
    return [{**{f: getattr(s, f) for f in fields}, **study_availability(s)}
            for s in discover_studies(studies_root)]


# ── capability registry (external services the workflow can attach) ────────────
# resources/capabilities.yaml is the committed, PUBLIC index of external capabilities —
# what exists, which stage it anchors to, when to use it, how to fall back. Endpoints and
# keys are NOT in it: kind=mcp resolves through the gitignored .mcp.json, kind=http_client
# through env vars/.env. A study pins what it actually used in its own resources.json
# (McpServerDecl, by NAME — private dev endpoints never land in committed artifacts).

CAPABILITIES_PATH = _REPO_ROOT / "resources" / "capabilities.yaml"
MCP_JSON_PATH = _REPO_ROOT / ".mcp.json"


def load_capabilities(path: str | Path | None = None) -> list[dict]:
    """Raw registry entries (list of dicts); [] when the registry is absent or empty.

    Lazy-imports yaml so environments without PyYAML can still use every other helper."""
    import yaml

    p = Path(path) if path is not None else CAPABILITIES_PATH
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    return [e for e in data if isinstance(e, dict) and e.get("name")]


def _capability_available(entry: dict, mcp_json: Path) -> tuple[bool, str]:
    """Static reachability from local config — NOT the live probe. The skill runs the
    entry's ``health`` check itself right before actually relying on the service."""
    cond = entry.get("available_when") or {}
    if "mcp_server" in cond:
        try:
            servers = json.loads(mcp_json.read_text(encoding="utf-8")).get("mcpServers", {})
        except (OSError, ValueError):
            servers = {}
        if cond["mcp_server"] in servers:
            return True, f"registered in {mcp_json.name}"
        return False, (f"'{cond['mcp_server']}' not in {mcp_json.name} — if its MCP tools are "
                       "visible in-session anyway, treat as available and probe `health`")
    if "env" in cond:
        from socioverse.external_events import _load_dotenv
        _load_dotenv()  # the same .env fallback the runtime clients use
        missing = [k for k in cond["env"] if not os.environ.get(k)]
        if missing:
            return False, "missing env: " + ", ".join(missing)
        return True, "env configured"
    return True, "no availability condition declared"


def capability_view(stage: str | None = None, path: str | Path | None = None,
                    mcp_json: str | Path | None = None) -> list[dict]:
    """``catalog_view``'s sibling for external SERVICES — what each build skill's generic
    "capability check" hook lists.

    ``stage`` filters to the entries anchored at that skill (their ``stages`` field);
    ``None`` returns all. Each entry is returned verbatim plus ``available`` /
    ``availability_note`` resolved from local config. Adding, removing, or changing a
    service is an edit to the registry only — the skills' hook text never changes.
    """
    mj = Path(mcp_json) if mcp_json is not None else MCP_JSON_PATH
    out = []
    for e in load_capabilities(path):
        if stage and stage not in (e.get("stages") or []):
            continue
        avail, note = _capability_available(e, mj)
        out.append({**e, "available": avail, "availability_note": note})
    return out
