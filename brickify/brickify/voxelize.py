"""Mesh -> occupancy grid at LEGO resolution.

The grid is 1 stud wide and 1 plate tall per cell. A stud is 2.5 plates tall,
so the mesh is stretched 2.5x vertically before voxelizing with cubic cells;
that keeps the model's proportions true once it's built from real bricks.
"""
from __future__ import annotations

import numpy as np
import trimesh
from scipy import ndimage

from .parts import PLATES_PER_STUD


def load(path: str, up: str = "y") -> trimesh.Trimesh:
    mesh = trimesh.load(path, force="mesh", process=True)
    if up == "z":  # rotate so +z becomes +y
        mesh.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
    return mesh


def voxelize(mesh: trimesh.Trimesh, length: int, shell: int | None = 2):
    """Solid occupancy grid (x, y, z) with the model's longest horizontal side
    spanning `length` studs. `shell` hollows the interior to that many cells
    (None = solid), which is how real LEGO sculptures save parts.
    Returns (grid, colours) where colours is an (x, y, z, 3) uint8 array or None.
    """
    m = mesh.copy()
    lo, hi = m.bounds
    horizontal = max(hi[0] - lo[0], hi[2] - lo[2])
    s = length / horizontal
    m.apply_translation(-lo)
    m.apply_scale(s)
    m.apply_scale([1.0, PLATES_PER_STUD, 1.0])

    surface = m.voxelized(pitch=1.0)
    grid = surface.matrix.copy()
    # Close pinholes, then fill the inside. Meshes with open bottoms (scans)
    # leak under a 3D fill, so fill slice by slice, where a hole only lets
    # one layer leak rather than the whole volume.
    grid = ndimage.binary_closing(grid, iterations=1) | grid
    solid = ndimage.binary_fill_holes(grid)
    if solid.sum() <= grid.sum() * 1.05:  # 3D fill leaked: fall back to per-layer fill
        solid = np.stack([ndimage.binary_fill_holes(grid[:, y, :]) for y in range(grid.shape[1])], axis=1)

    if shell is not None:
        inner = ndimage.binary_erosion(solid, iterations=shell)
        solid = solid & ~inner

    colours = _sample_colours(m, surface, solid)
    return solid.astype(bool), colours


def _sample_colours(m: trimesh.Trimesh, surface, solid):
    """Colour of the nearest surface point for every filled cell, if the mesh has any."""
    visual = m.visual
    try:
        if visual.kind == "texture":
            visual = visual.to_color()
        if visual.kind != "vertex" and visual.kind != "face":
            return None
    except Exception:
        return None
    idx = np.argwhere(solid)
    centres = surface.indices_to_points(idx) if hasattr(surface, "indices_to_points") else idx + 0.5
    _, _, tri = trimesh.proximity.closest_point(m, centres)
    face_colours = m.visual.face_colors[tri][:, :3] if m.visual.kind == "face" else m.visual.vertex_colors[m.faces[tri]].mean(axis=1)[:, :3]
    out = np.zeros((*solid.shape, 3), dtype=np.uint8)
    out[tuple(idx.T)] = face_colours.astype(np.uint8)
    return out
