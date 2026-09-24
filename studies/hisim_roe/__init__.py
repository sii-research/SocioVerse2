"""hisim_roe — HiSim hybrid social-movement simulation, from-scratch on SocioVerse2 Core (Path B).

Importing the package registers its four abc implementations (hisim.pop / hisim.twitter_env /
hisim.hybrid_decision / hisim.metrics) so engine.build_simulator can resolve them.
"""

from __future__ import annotations

from . import model  # noqa: F401  (side effect: @register decorators run)
from .model import make_hisim_bundles  # noqa: F401

__all__ = ["make_hisim_bundles", "model"]
