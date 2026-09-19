# demo/ — the thing that has to work when the wifi dies

```bash
scripts/demo_safe.sh            # serve the canned snapshot, offline. This is the panic button.
scripts/demo_safe.sh --check    # start it, score every endpoint, stop, exit 0
.venv/bin/python -m demo.snapshot   # re-freeze a run after core/ api/ render/ change
```

| File | What it is |
|---|---|
| `SCRIPT.md` | The 3-minute demo, with timings. Read it out loud before presenting. |
| `CHECKLIST.md` | What to check at T−60 and T−10. |
| `snapshot.py` | Runs the real pipeline over the real bin and freezes everything to `canned/`. |
| `check.py` | Is a snapshot internally consistent? Disk only, no server. |
| `serve.py` | The real API with `DEMO_SAFE=1`, pointed at a snapshot, network guard on. |
| `verify.py` | Asks every endpoint a question over loopback and scores the answers. |
| `netguard.py` | Makes a non-loopback `connect()` raise. "Offline" as a property, not a promise. |
| `canned/` | The frozen run from `data/real/inventory.json` — the real bin, long tail and all. |
| `canned-rich/` | The same pipeline on `fixtures/inventory.json`. The fallback if the real bin builds something too small to show. |

A snapshot directory is exactly what `api.engine` reads in `DEMO_SAFE` (`inventory.json`,
`build.json`, `report.json`, `steps.json`, `tape.jsonl`) plus the recipe an edit needs
(`composition.json`), the export (`model.ldr`), the provenance (`meta.json`) and the rendered
manual (`manual/`). `demo/serve.py` swaps it in by re-pointing one attribute, `engine.FIXTURES`,
so nothing in `api/` has to know this package exists.
