# Credits

This project stands on other people's work. Every dependency here was verified — licence and
maintenance status — before adoption; see `docs/07-tooling-decisions.md`.

| Project | Licence | What we use it for |
|---|---|---|
| [**bricknet**](https://github.com/kulits/BrickNet) | MIT | The bundled connector table (`labels.json.xz`) — stud / anti-stud / axle poses for 14,603 LDraw parts. This replaces our entire hand-written part-metadata component. Its `graph.parse_ldr` also cross-checks our geometry in the test suite. |
| [**LDraw Parts Library**](https://library.ldraw.org/) | CC BY 4.0 (CCAL) | Part geometry, the official parts catalog (`library.csv`), and `LDConfig.ldr` colours. Attribution to "The LDraw Parts Library" is the required form. |
| [**three.js**](https://threejs.org/) `LDrawLoader` | MIT | Browser rendering, with native `0 STEP` build-step support. |
| [**LeoCAD**](https://www.leocad.org/) | GPL-2.0 | Per-step isometric renders (invoked as a subprocess, not linked). |
| [**WeasyPrint**](https://weasyprint.org/) | BSD | PDF page assembly. |
| [**SAM 2**](https://github.com/facebookresearch/sam2) | Apache-2.0 | Class-agnostic pile segmentation. |
| [**Brickognize**](https://brickognize.com/) | free public API | Part identification from crops. See Vidal, Vallicrosa, Martí & Barnada, *Sensors* 23(4):1898 (2023). |
| [**BrickGPT / LegoGPT**](https://github.com/AvaLovelace1/BrickGPT) | MIT | Reference for stability and connectivity analysis. |
| [**OR-Tools**](https://developers.google.com/optimization) | Apache-2.0 | Inventory-constrained tiling as a hard constraint. |

**Licence posture:** MIT/Apache/BSD throughout, Python 3.11+. We deliberately did *not* adopt
`pyldraw3`, `legolization` or `hbmartin/rebrickable` — all GPL-3.0 and Python ≥3.12 — to keep the
backend clean and the runtime pinned. Reasoning in `docs/07-tooling-decisions.md`.

LEGO® is a trademark of the LEGO Group, which does not sponsor, authorize or endorse this project.
No LEGO wordmark, logo or corporate font appears in our branding.
