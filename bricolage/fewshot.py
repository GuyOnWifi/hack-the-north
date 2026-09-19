"""Few-shot examples for the LEGO LLM harness — real StableText2Brick rows plus
a few hand-designed corbelled shapes, all validated for vertical connectivity
(every non-ground brick rests on the layer directly below, no collisions,
in-bounds). Diverse archetypes on purpose: tall/slender, thin-stem-wide-top
(the case we kept failing), blocky, and hollow-detail — so the model doesn't
collapse every request into a flat bench.

Grammar reminder: `hxw (x,y,z)` occupies x..x+h-1 (h along x) and y..y+w-1
(w along y) at layer z.
"""

EXAMPLES = [
    # tall / slender vertical (real dataset)
    ('Tall guitar with a long neck and a geometric body.',
     '6x2 (0,18,0)\n6x2 (0,18,1)\n6x2 (0,18,2)\n4x2 (1,18,3)\n4x2 (1,18,4)\n6x2 (0,18,5)\n6x2 (0,18,6)\n2x2 (2,18,7)\n2x1 (2,18,8)\n2x1 (2,18,9)\n2x1 (2,18,10)\n2x1 (2,18,11)\n2x1 (2,18,12)\n2x1 (2,18,13)\n2x1 (2,18,14)\n2x2 (2,18,15)\n2x2 (2,18,16)\n2x2 (2,18,17)'),
    # tall: thin trunk + wide corbelled canopy
    ('A tree with a thin trunk and a wide, rounded canopy.',
     '1x1 (10,10,0)\n1x1 (10,10,1)\n1x1 (10,10,2)\n2x2 (9,9,3)\n4x2 (8,8,4)\n4x2 (8,10,4)\n6x2 (7,7,5)\n6x2 (7,9,5)\n6x2 (7,11,5)\n4x2 (8,8,6)\n4x2 (8,10,6)\n2x2 (9,9,7)'),
    # thin stem + wide top (flower) — the critical case
    ('A flower with a thin stem and a blossom on top.',
     '1x1 (10,10,0)\n1x1 (10,10,1)\n1x1 (10,10,2)\n1x1 (10,10,3)\n3x1 (9,10,4)\n1x3 (9,9,5)\n1x3 (10,9,5)\n1x3 (11,9,5)\n1x1 (10,10,6)'),
    # thin stem + wide top (mushroom)
    ('A mushroom with a narrow stem and a wide domed cap.',
     '2x2 (9,9,0)\n2x2 (9,9,1)\n2x2 (9,9,2)\n4x2 (8,8,3)\n4x2 (8,10,3)\n6x2 (7,7,4)\n6x2 (7,9,4)\n6x2 (7,11,4)\n4x2 (8,8,5)\n4x2 (8,10,5)'),
    # low blocky object (real dataset)
    ('Rectangular car with a ridged top.',
     '1x6 (3,12,0)\n1x8 (3,4,0)\n2x2 (2,2,0)\n1x1 (1,2,0)\n4x2 (0,18,0)\n2x1 (0,17,0)\n1x2 (0,15,0)\n1x8 (0,7,0)\n2x4 (0,3,0)\n1x4 (3,13,1)\n1x8 (3,5,1)\n2x2 (2,17,1)\n2x1 (1,2,1)\n4x1 (0,19,1)\n2x6 (0,13,1)\n2x1 (0,12,1)\n2x6 (0,6,1)\n2x1 (0,5,1)\n4x2 (0,3,1)\n1x4 (3,4,2)\n2x6 (2,14,2)\n2x6 (2,8,2)\n1x2 (1,16,2)\n1x8 (1,8,2)\n2x4 (1,4,2)\n2x2 (0,18,2)'),
    # hollow interior detail (real dataset)
    ('Rectangular pot with a hollow center.',
     '1x8 (9,10,0)\n1x8 (9,2,0)\n2x2 (8,18,0)\n1x1 (8,3,0)\n6x2 (2,18,0)\n6x1 (2,3,0)\n2x6 (0,14,0)\n2x6 (0,8,0)\n2x6 (0,2,0)\n1x6 (9,12,1)\n1x8 (9,4,1)\n1x1 (9,2,1)\n4x2 (6,18,1)\n8x1 (2,3,1)\n6x2 (0,18,1)\n2x1 (0,17,1)\n2x2 (0,15,1)\n2x6 (0,9,1)\n2x6 (0,3,1)\n2x1 (0,2,1)'),
]
