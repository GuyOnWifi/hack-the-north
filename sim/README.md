# Brick drop (sim/)

A practice plate for Lane A's brick scanner. Picks random pieces from the LDraw
library, colours them from a colour-theory palette, drops them onto a white
plate with real physics, and photographs the plate from straight above. Every
photo comes with exact ground truth, so it can both **test** the scanner and
**train** it.

## Run

```bash
# once: the parts library (145 MB zip -> ~/ldraw). Set LDRAW_DIR if it lives elsewhere.
curl -LO https://library.ldraw.org/library/updates/complete.zip && unzip -q complete.zip -d ~

cd sim && npm install && npm run dev      # http://localhost:3220
```

Nothing is pre-baked per piece. The dev server (`server/ldraw.ts`) indexes the
library once (`.cache/catalog.json`, ~3,700 loose-piece shapes after dropping
stickers, prints, minifigs, baseplates...) and serves each requested part with
all its subfiles in one response. The browser parses a shape once and reuses the
geometry for every copy and colour.

## What it writes (all under `sim/out/`)

**Save this photo** -> `out/photos/plate-<time>.png` + `.json` answer sheet:
every piece's part number, colour, visible bounding box (normalised, same
convention as the app's `crop`), how much of it is unobstructed (`visible`), and
an `inventory` of part + colour counts. Score a scanner run against it:

```bash
npm run score -- out/photos/plate-XXXX.json predictions.json
```

**Make training set** -> `out/set-<time>/`, a YOLO dataset Ultralytics trains on as is:

```
images/{train,val}/00001.jpg    labels/{train,val}/00001.txt    data.yaml
meta/00001.json (full answer sheet)    classes.json    counts.csv
```

```bash
yolo detect train data=sim/out/set-XXXX/data.yaml model=yolo11s.pt imgsz=1280
```

- The class is the piece shape (LDraw part number). Colour is in `meta/` and
  `counts.csv`; it is usually better read from the detected crop than learned as
  classes x colours.
- The pieces in the tray are the classes. Each photo gets a different mix of
  them, a new palette, pile size and crowding; light, table, exposure and camera
  tilt vary too, so the model does not learn one studio look.
- Pieces less than 25% visible are left unlabelled on purpose.
- Every seventh photo goes to `val`. Keep the tab in front while a set runs:
  browsers pause background tabs.

## Layout

- `server/ldraw.ts` catalog, part packs, saving photos and datasets
- `src/parts.ts` shape loading + cache, plastic materials, collider hulls
- `src/world.ts` scene, plate, physics (Rapier), cameras, scene variation
- `src/labels.ts` ground truth from an id-colour render pass
- `src/palette.ts` OKLCH harmonies snapped to real brick colours
- `src/main.ts`, `index.html`, `src/style.css` the panel
