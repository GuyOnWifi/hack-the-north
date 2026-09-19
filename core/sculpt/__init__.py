"""`sculpt` -- the freeform backend, for the things no parametric generator covers.

"a dog", "a heart", "my initials". The LLM emits a shape as bottom-to-top ASCII layers
(`parse.py`); we legalize that voxel grid into real bricks from a real bin (`tile.py`). Same
output type as `compose` and `recall`: a `Build` that has been through `validate()`.
"""

from ..model import Inventory
from .parse import EMPTY, LayerMap, SculptError, parse
from .tile import SculptResult, tile

__all__ = ["EMPTY", "LayerMap", "SculptError", "SculptResult", "parse", "sculpt", "tile"]


def sculpt(spec: dict | str, inventory: Inventory, **kw) -> SculptResult:
    """Layer map (raw, as the LLM emits it) -> validated Build. Raises SculptError if malformed."""
    return tile(parse(spec), inventory, **kw)
