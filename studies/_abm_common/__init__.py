"""SocioVerse-ABM umbrella — the shared adapter for all abm_* studies.

Importing this registers the four generic providers (abm.env / abm.pop / abm.decision /
abm.collector) with Core's registry; each abm_<task> study then needs only artifacts that
select its task by name. See README.md and the manifest for the catalog of studies.
"""
from . import providers  # noqa: F401  (side effect: @register the 4 umbrella providers)
from .bundles import make_abm_bundles, task_metrics  # noqa: F401
from .seam import abm_available, abm_missing_deps, abm_present, abm_root, load_task  # noqa: F401

__all__ = ["make_abm_bundles", "task_metrics", "load_task", "abm_root", "abm_available",
           "abm_present", "abm_missing_deps"]
