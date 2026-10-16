"""circlepack: pack n equal circles of maximal radius in a fixed convex container."""
import os as _os

# The pipeline evaluates many tiny vectorised expressions; multi-threaded BLAS
# makes those 10-100x slower and oversubscribes cores when running parallel
# starts. Respect explicit user settings, otherwise force one thread.
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    _os.environ.setdefault(_var, "1")

from .containers import Container, make_container  # noqa: E402
from .search import SearchConfig, StartResult, run_start  # noqa: E402
from .parallel import run_many  # noqa: E402
from .polish import polish  # noqa: E402
from .energy import feasible_radius  # noqa: E402

__version__ = "0.1.0"
__all__ = ["Container", "make_container", "SearchConfig", "StartResult", "run_start",
           "run_many", "polish", "feasible_radius", "__version__"]
