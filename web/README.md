# Lane C: the app (web/)

The phone-first PWA: scan a pile, review what was found, ask for a build, watch
the agent tape, change it in plain words, then follow a step-by-step 3D manual
or print it. Next.js 16 + react-three-fiber. It talks to Lane B's API
(`bricolage/server.py`) and never blocks on it: when the API is down it falls
back to `fixtures/`.

## Run

```bash
python bricolage/server.py          # Lane B API on :8017 (add PROVIDER=claude_cli for the real designer)
cd web && npm install && npm run dev -- -p 3210 -H 0.0.0.0
```

Open http://localhost:3210, or `http://<your-LAN-IP>:3210` on a phone on the
same wifi. The app proxies `/bricolage/*` to `BRICOLAGE_URL`
(default `http://127.0.0.1:8017`), so phones never talk to :8017 directly.

`npm run dev` / `npm run build` first copy `../fixtures` into
`public/bricolage-fixtures` (the offline fallback).

## How it plugs into Lane B

| App screen | Lane B call |
|---|---|
| My bricks → Find builds | `POST /api/inventory` with the reviewed pile |
| Build ideas / home search → Designing | `GET /api/build_stream` (live tape), then `GET /api/ldr` |
| Change it | `POST /api/edit`, `/try_another`, `/undo`, `/redo` |
| Build screens after a reload | `GET /api/state` |

The live design lives at `/build/live`; `/build/car` etc. are bundled sample
models. Report `human` strings are rendered verbatim.

## Rendering Lane B's models

`/api/ldr` references plain part files (`3001.dat`). The app appends
`public/ldraw/parts.pack.ldr`, a 100 KB bundle of exactly the LDraw files the
build system can emit, so nothing is fetched at render time and no parts
library is needed on the machine. Regenerate it when `bricolage/meta.py` or the
generators gain a part:

```bash
LDRAW_DIR=~/ldraw npm run ldraw-pack    # needs the LDraw library (complete.zip from ldraw.org)
```

## Other scripts

- `npm run fixtures`: rebuilds the sample builds, the sample scanned pile
  (made from Lane B's usable parts) and part images.
- `npm run typecheck`, `npm run lint`.

## Layout

- `src/app/*`: one folder per screen (splash, home, scan, inventory, builds,
  create, build/[id]/{view,steps,parts,print}).
- `src/lib/bricolage.ts`: typed API client (the contracts in HANDOFF.md).
- `src/lib/live.ts`: the live design session store.
- `src/lib/ldraw.ts`: loading, step indexing, off-screen thumbnails.
- `src/components/three/ModelView.tsx`: the one 3D view (display turntable,
  manual steps with the purple new-part outline, timeline ghosts).
