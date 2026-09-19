"""Few-shot exemplars baked from StableText2Brick (BrickGPT dataset):
small, physics-validated 3D models that teach the  grammar
and how to build recognizable 3D form from plain bricks. Credit: Pun et al.,
ICCV 2025 (StableText2Brick / BrickGPT)."""

EXAMPLES = [
    ('Simple bench with rectangular top and short legs.',
     '1x1 (16,19,0)\n1x1 (16,17,0)\n2x1 (0,19,0)\n2x1 (0,17,0)\n1x1 (16,19,1)\n1x1 (16,17,1)\n2x1 (0,19,1)\n2x1 (0,17,1)\n1x1 (16,18,2)\n8x1 (9,19,2)\n8x1 (9,17,2)\n1x1 (8,19,2)\n1x1 (8,17,2)\n6x1 (2,17,2)\n8x1 (0,19,2)\n2x2 (0,17,2)\n2x4 (16,16,3)\n2x4 (14,16,3)\n2x4 (12,16,3)\n6x2 (6,18,3)\n6x2 (6,16,3)\n6x2 (0,18,3)\n6x2 (0,16,3)'),
    ('Bench composed of interlocking geometric pieces.',
     '2x2 (16,18,0)\n2x1 (16,17,0)\n1x1 (11,19,0)\n1x2 (11,17,0)\n1x1 (6,19,0)\n1x2 (6,17,0)\n1x1 (0,19,0)\n1x2 (0,17,0)\n6x1 (12,19,1)\n6x2 (12,17,1)\n4x1 (8,17,1)\n6x2 (6,18,1)\n6x2 (0,18,1)\n8x1 (0,17,1)\n2x2 (16,17,2)\n4x1 (14,19,2)\n8x1 (6,19,2)\n1x1 (5,19,2)\n4x1 (1,19,2)\n1x2 (0,18,2)\n1x1 (0,17,2)\n2x2 (16,18,3)\n8x1 (8,19,3)\n8x1 (0,19,3)\n1x1 (0,18,3)'),
    ('Minimalist bench with a rectangular shape.',
     '2x4 (16,16,0)\n2x4 (0,16,0)\n2x4 (16,16,1)\n2x4 (0,16,1)\n1x4 (17,16,2)\n2x4 (15,16,2)\n6x2 (9,18,2)\n6x2 (9,16,2)\n6x2 (3,18,2)\n6x2 (3,16,2)\n2x4 (1,16,2)\n1x4 (0,16,2)\n2x4 (16,16,3)\n6x2 (10,17,3)\n8x1 (8,19,3)\n8x1 (8,16,3)\n6x2 (4,17,3)\n8x1 (0,19,3)\n4x2 (0,17,3)\n8x1 (0,16,3)'),
    ('Long bench with rectangular seat and multiple supports.',
     '2x4 (13,16,0)\n2x4 (8,16,0)\n1x4 (3,16,0)\n1x1 (14,19,1)\n1x1 (14,16,1)\n6x2 (12,17,1)\n1x1 (8,19,1)\n1x1 (8,16,1)\n6x2 (6,17,1)\n1x1 (3,19,1)\n1x1 (3,16,1)\n6x2 (0,17,1)\n2x4 (16,16,2)\n2x4 (14,16,2)\n1x4 (13,16,2)\n6x2 (7,18,2)\n6x2 (7,16,2)\n6x2 (1,18,2)\n6x2 (1,16,2)\n1x4 (0,16,2)\n1x2 (17,18,3)\n6x2 (11,18,3)\n1x2 (10,18,3)\n4x2 (6,18,3)\n6x2 (0,18,3)'),
]
