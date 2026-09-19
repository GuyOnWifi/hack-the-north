"""HTML manual -> PDF, down a ladder whose bottom rung is still a real deliverable.

WHY there are three rungs and not one
-------------------------------------
WeasyPrint is the documented choice (D17) but it links against cairo/pango/gdk-pixbuf, which
are system libraries we cannot count on at hour 34 on a borrowed machine, and which cannot be
installed over dead conference wifi. Headless Chrome is the rung underneath it: it is already
on every laptop at the event, it needs no install and no network, and `--print-to-pdf` honours
the same `@page` CSS. Below that, the HTML itself -- self-contained, A4-landscape CSS, "print
to PDF" in any browser.

So:  weasyprint -> chrome -> html-only,  and this function NEVER raises. "No PDF" must not
take the manual down with it.

The HTML is self-contained (images are data URIs), so `base_url` only matters if a caller
deliberately asked manual_html for external image references.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
from dataclasses import dataclass

BACKENDS = ("auto", "weasyprint", "chrome", "html-only")

_CHROME_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                 "chrome", "microsoft-edge")
_CHROME_BUNDLES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)


@dataclass(frozen=True, slots=True)
class PdfResult:
    ok: bool
    path: pathlib.Path          # the PDF when ok, otherwise the HTML we wrote instead
    html_path: pathlib.Path
    backend: str                # "weasyprint" | "chrome" | "html-only"
    note: str = ""


def weasyprint_available() -> bool:
    """True only if WeasyPrint imports -- a bare `find_spec` lies when cairo is missing."""
    try:
        import weasyprint  # noqa: F401
    except Exception:
        return False
    return True


def chrome_path() -> str | None:
    """Path to a Chromium-family browser we can drive headless, or None."""
    for name in _CHROME_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for bundle in _CHROME_BUNDLES:
        if pathlib.Path(bundle).is_file():
            return bundle
    return None


INSTALL_HINT = (
    "No PDF: neither WeasyPrint nor a headless Chrome was available, so the manual was "
    "written as HTML instead -- open it in any browser and print to PDF, the page CSS is "
    "already A4 landscape. To get PDFs directly: `pip install weasyprint`, which also needs "
    "the cairo/pango system libraries (macOS: `brew install pango libffi`)."
)


def _render_weasyprint(html: str, pdf_path: pathlib.Path, base_url: str | None) -> str | None:
    """Returns None on success, or a human sentence explaining the failure."""
    try:
        import weasyprint
        weasyprint.HTML(string=html, base_url=base_url).write_pdf(str(pdf_path))
    except Exception as exc:  # a broken cairo throws at render time, not at import time
        return f"WeasyPrint imported but failed to render ({exc})."
    return None


def _render_chrome(exe: str, html_path: pathlib.Path, pdf_path: pathlib.Path,
                   timeout: float = 45.0) -> str | None:
    """Headless `--print-to-pdf`.

    MEASURED, do not "fix" this: passing `--user-data-dir` makes Chrome on macOS hang
    forever instead of printing and exiting. Its own default headless profile works and
    coexists with a Chrome the user already has open, so we let it use that.
    """
    cmd = [exe, "--headless", "--disable-gpu", "--no-sandbox",
           "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
           "--no-pdf-header-footer", "--virtual-time-budget=15000",
           f"--print-to-pdf={pdf_path}", html_path.as_uri()]
    try:
        subprocess.run(cmd, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"Headless Chrome failed to produce a PDF ({exc})."
    # Chrome exits 0 and writes noise to stderr even when it worked, so trust the file.
    if not pdf_path.exists() or pdf_path.stat().st_size < 1024:
        return "Headless Chrome ran but produced no PDF."
    return None


def html_to_pdf(html: str, out_pdf, base_url: str | None = None,
                backend: str = "auto") -> PdfResult:
    """Write `html` beside `out_pdf`, then convert it with the best backend present."""
    if backend not in BACKENDS:
        raise ValueError(f"backend must be one of {BACKENDS}, got {backend!r}")

    pdf_path = pathlib.Path(out_pdf)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    html_path = pdf_path.with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")

    tried: list[str] = []

    if backend in ("auto", "weasyprint") and weasyprint_available():
        err = _render_weasyprint(html, pdf_path, base_url or html_path.parent.as_uri())
        if err is None:
            return PdfResult(True, pdf_path, html_path, "weasyprint",
                             f"{pdf_path.name} written with WeasyPrint.")
        tried.append(err)
    elif backend == "weasyprint":
        tried.append("WeasyPrint is not installed.")

    if backend in ("auto", "chrome"):
        exe = chrome_path()
        if exe is None:
            tried.append("No Chromium-family browser found.")
        else:
            err = _render_chrome(exe, html_path, pdf_path)
            if err is None:
                return PdfResult(True, pdf_path, html_path, "chrome",
                                 f"{pdf_path.name} written with headless Chrome.")
            tried.append(err)

    note = " ".join(tried + [INSTALL_HINT]) if tried else INSTALL_HINT
    return PdfResult(False, html_path, html_path, "html-only", note)
