"""Parametric subassembly generators.

The ecosystem sweep turned up 90 findings and ZERO prior art for this component. It is what
makes "build me a rover" look designed rather than like a blob, so it gets the time freed up by
adopting bricknet/SAM 2/LeoCAD elsewhere.

Contract every generator honours:
  * it returns only placements it could actually afford from the Allocator;
  * it declares its attachment points, which are FROZEN when a subtree is regenerated during
    an edit -- that is what keeps the cabin fitting after "make the chassis longer";
  * it returns None rather than an invalid or unaffordable structure. Never a partial build.
"""

from .registry import GENERATORS, SubResult, generator, generate  # noqa: F401
from . import basic  # noqa: F401  (registers the built-ins)
from .basic import reset_ids  # noqa: F401
from . import extra  # noqa: F401  (registers the silhouette generators)
