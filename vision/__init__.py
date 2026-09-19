"""Photo -> inventory.

Two implementations behind one interface, selected by environment variable:

    VISION_SEG=opencv | sam2          how we find the bricks
    VISION_CLS=brickognize | model    how we name them

The classical path (opencv + brickognize) is the FLOOR. It works with no GPU, no training and no
model download, and it is never deleted. Anything else is an upgrade that has to beat it on the
real-photo eval set before it ships.
"""

from .pipeline import analyse_photo, analyse_folder  # noqa: F401
