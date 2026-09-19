"""The render lane: Build + steps -> PNGs -> HTML manual -> PDF.

The load-bearing test in here is `test_survives_a_bare_machine`: the whole path has to run
with neither LeoCAD nor WeasyPrint installed, because that is the machine we will demo on.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest
from PIL import Image

from render import (RenderOpts, load_build, load_steps, make_manual, manual_html,
                    render_part, render_steps)
from render import pdf as pdf_mod
from render import steps_png
from render.manual_html import callouts
from render.steps_png import MANUAL_BLUE, ldraw_rgb

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"
SMALL = RenderOpts(width=420, height=320, supersample=1)


@pytest.fixture(scope="module")
def build():
    return load_build(FIXTURES / "build.json")


@pytest.fixture(scope="module")
def steps(build):
    # The build lane's steps reference parts by id, so the Build has to come along.
    return load_steps(FIXTURES / "steps.json", build)


@pytest.fixture(scope="module")
def rendered(build, steps, tmp_path_factory):
    out = tmp_path_factory.mktemp("steps")
    return render_steps(build, steps, out, SMALL)


# ---------------------------------------------------------------- fixtures load

def test_fixtures_parse_into_the_core_model(build, steps):
    raw = json.loads((FIXTURES / "build.json").read_text())
    assert len(build.parts) == len(raw["parts"]) > 0
    assert build.name == raw["name"]
    # every step part is a part of the build, and every build part is in exactly one step
    flat = [p for g in steps for p in g]
    assert sorted(p.id for p in flat) == sorted(p.id for p in build.parts)
    for p in flat:
        assert all(isinstance(v, int) for v in p.pos)   # invariant 1, still holding
        assert p.rot in (0, 90, 180, 270)


# ---------------------------------------------------------------- step PNGs

def test_one_png_per_step(rendered, steps):
    assert len(rendered.images) == len(steps)
    for path in rendered.images:
        assert path.exists() and path.stat().st_size > 0


def _histogram(path_or_img):
    img = path_or_img if isinstance(path_or_img, Image.Image) else Image.open(path_or_img)
    return img.convert("RGB").getcolors(maxcolors=1 << 24)


def _ink(path_or_img) -> int:
    return sum(n for n, c in _histogram(path_or_img) if c != MANUAL_BLUE)


def test_step_images_are_not_blank(rendered):
    """A blank page is the failure mode that looks like success, so assert against it."""
    for path in rendered.images:
        hist = _histogram(path)
        total = sum(n for n, _ in hist)
        # Ink scales with how many parts a step adds, and the build lane's first step is a
        # 2-part sub-assembly, so a fixed 15% floor fails on a legitimately sparse page.
        # What we actually care about is "not blank".
        assert _ink(path) / total > 0.005, f"{path.name} is blank"
        # top / +x / +z faces are three different shades: if fewer show up, the box maths
        # collapsed and we are drawing flat silhouettes instead of bricks.
        shades = {c for _, c in hist if c not in (MANUAL_BLUE, (17, 17, 17))}
        assert len(shades) >= 3, f"{path.name} has no face shading"


def test_the_model_grows_and_the_camera_does_not_move(rendered):
    """Ink is non-decreasing: one fitted camera, and each step only adds parts."""
    ink = [_ink(p) for p in rendered.images]
    assert ink == sorted(ink)
    assert ink[-1] > ink[0]


def test_already_built_parts_are_washed_out(build):
    """The same parts must render paler as history than they do as this step's new parts."""
    from render.steps_png import _box_of, fit_camera, render_scene
    parts = list(build.parts[:6])
    cam = fit_camera([_box_of(p) for p in parts], SMALL)

    def mean_distance_from_background(img):
        hist = _histogram(img)
        tot = sum(n for n, _ in hist)
        return sum(n * sum(abs(a - b) for a, b in zip(c, MANUAL_BLUE))
                   for n, c in hist) / tot

    fresh = mean_distance_from_background(render_scene(parts, [], cam, SMALL))
    stale = mean_distance_from_background(render_scene([], parts, cam, SMALL))
    assert stale < fresh, "highlighting does nothing; every step page would look identical"


def test_rendering_is_deterministic(build, steps, tmp_path):
    a = render_steps(build, steps, tmp_path / "a", SMALL)
    b = render_steps(build, steps, tmp_path / "b", SMALL)
    for pa, pb in zip(a.images, b.images):
        assert pa.read_bytes() == pb.read_bytes()


def test_part_thumbnails_are_transparent_and_drawn():
    img = render_part("3001", 4, size=96)
    assert img.mode == "RGBA" and img.size == (96, 96)
    opaque = sum(n for n, a in img.getchannel("A").getcolors(256) if a > 200)
    assert 0.15 < opaque / (96 * 96) < 0.95, "thumbnail is empty or completely filled"


def test_unknown_part_still_renders(build, tmp_path):
    """An off-whitelist part must not blank the page -- it draws as a 1x1 placeholder."""
    from core.model import Build, Placed
    b = Build(id="x", name="x", parts=(Placed("p1", "9999zzz", 4, (0, 0, 0)),))
    r = render_steps(b, [list(b.parts)], tmp_path, SMALL)
    assert _ink(r.images[0]) > 0


def test_ldraw_colours_come_from_the_palette():
    r, g, bl = ldraw_rgb(4)
    assert r > 150 and g < 80 and bl < 80          # 4 is red
    assert sum(ldraw_rgb(15)) > 700                # 15 is white
    assert sum(ldraw_rgb(0)) < 200                 # 0 is black
    assert ldraw_rgb(999999) == (150, 150, 150)    # unknown code degrades, never raises


# ---------------------------------------------------------------- HTML

@pytest.fixture(scope="module")
def doc(build, steps, rendered):
    return manual_html(build, steps, rendered.images, embed=True)


def test_one_page_per_step_plus_cover_and_parts_list(doc, steps):
    assert doc.count('class="page') == len(steps) + 2
    assert doc.count('class="page step"') == len(steps)
    assert doc.count('class="page cover"') == 1
    assert doc.count('class="page list"') == 1
    for i in range(1, len(steps) + 1):
        assert f'<div class="stepno">{i}</div>' in doc


def test_callout_counts_match_the_steps(doc, steps):
    for i, group in enumerate(steps, 1):
        rows = callouts(group)
        assert sum(c.qty for c in rows) == len(group)
        for c in rows:
            assert f'{c.qty}&#215;' in doc          # the "2x" a real manual prints
            assert c.part in doc


def test_cover_and_parts_list_carry_the_real_totals(doc, build):
    assert f'<div class="n">{len(build.parts)}</div>' in doc
    assert f'<div class="n">{len(build.counts)}</div>' in doc
    assert f"Parts list &mdash; {len(build.parts)} pieces" in doc
    assert "does not sponsor, authorize or endorse" in doc


def test_html_is_self_contained_when_embedded(doc):
    assert 'src="data:image/png;base64,' in doc
    assert 'src="step_' not in doc


def test_html_refuses_a_mismatched_image_list(build, steps, rendered):
    with pytest.raises(ValueError):
        manual_html(build, steps, rendered.images[:-1])


# ---------------------------------------------------------------- PDF / degradation

def test_pdf_falls_back_to_html_with_no_engine_at_all(monkeypatch, tmp_path):
    monkeypatch.setattr(pdf_mod, "weasyprint_available", lambda: False)
    monkeypatch.setattr(pdf_mod, "chrome_path", lambda: None)
    res = pdf_mod.html_to_pdf("<html><body>hi</body></html>", tmp_path / "m.pdf")
    assert res.ok is False
    assert res.backend == "html-only"
    assert res.path.suffix == ".html" and res.path.read_text().startswith("<html>")
    assert "weasyprint" in res.note.lower() and "cairo" in res.note.lower()
    assert not (tmp_path / "m.pdf").exists()


def test_pdf_rejects_an_unknown_backend(tmp_path):
    with pytest.raises(ValueError):
        pdf_mod.html_to_pdf("<html></html>", tmp_path / "m.pdf", backend="latex")


@pytest.mark.skipif(pdf_mod.chrome_path() is None, reason="no Chromium-family browser")
def test_headless_chrome_produces_a_real_pdf(doc, tmp_path):
    """The rung that actually runs on this machine. WeasyPrint's rung is untested here."""
    res = pdf_mod.html_to_pdf(doc, tmp_path / "manual.pdf", backend="chrome")
    assert res.ok, res.note
    assert res.backend == "chrome"
    data = res.path.read_bytes()
    assert data.startswith(b"%PDF-") and len(data) > 50_000
    assert data.count(b"/Type /Page\n") >= 9 or data.count(b"/Type/Page") >= 9


def test_explicit_leocad_backend_says_so_instead_of_pretending(monkeypatch, build, steps,
                                                               tmp_path):
    monkeypatch.setattr(steps_png, "leocad_path", lambda: None)
    with pytest.raises(RuntimeError, match="leocad"):
        render_steps(build, steps, tmp_path, SMALL, backend="leocad")


def test_survives_a_bare_machine(monkeypatch, build, steps, tmp_path):
    """No LeoCAD, no WeasyPrint, no Chrome, no network. Still a manual."""
    monkeypatch.setattr(steps_png, "leocad_path", lambda: None)
    monkeypatch.setattr(pdf_mod, "weasyprint_available", lambda: False)
    monkeypatch.setattr(pdf_mod, "chrome_path", lambda: None)

    r = make_manual(build, steps, tmp_path, SMALL)

    assert r.ok
    assert r.steps.backend == "iso"
    assert len(r.steps.images) == len(steps)
    assert r.html_path.exists() and r.html_path.suffix == ".html"
    assert r.pdf.ok is False
    assert len(r.thumbs) == len(build.counts)
    assert all(p.exists() for p in r.thumbs.values())
    assert r.hero is not None and r.hero.exists()

    html = r.html_path.read_text()
    assert html.count('class="page step"') == len(steps)
    assert any("LeoCAD not installed" in n for n in r.notes)
    assert any("WeasyPrint" in n for n in r.notes)
