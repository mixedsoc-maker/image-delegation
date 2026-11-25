#!/usr/bin/env python3
"""Image/PDF preprocessing for the image-delegation skill.

Every subcommand prints ONLY text (paths + metadata). Nothing here ever puts
pixels into an agent's context; viewing happens only in image-inspector via Read.

Backends: poppler (pdftotext/pdfimages/pdftoppm) -> PyMuPDF fallback;
Pillow for raster work; Playwright (Python, else `npx playwright`) for screenshots.

Usage: sh imgtool.sh <subcommand> -h
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import limits as _limits  # noqa: E402

PROJECT_DIR = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".ico", ".heic", ".avif"}
DEFAULT_OUT = os.environ.get("IMGTOOL_OUT") or os.path.join(PROJECT_DIR, ".claude", "tmp", "image-delegation")
DEFAULT_MAX_SIDE = 1568

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


# ---------------------------------------------------------------- helpers
def limits(a=None) -> dict:
    ov = {}
    if a is not None:
        ov = {"HARD_LIMIT": getattr(a, "hard_limit", None), "DEFAULT_BUDGET": getattr(a, "default_budget", None)}
    return _limits.load(ov)


def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def out_dir(path: str | None) -> str:
    d = os.path.abspath(path or DEFAULT_OUT)
    os.makedirs(d, exist_ok=True)
    if not path:  # keep the project-local temp dir out of git
        gi = os.path.join(os.path.dirname(d), ".gitignore")
        if os.path.basename(os.path.dirname(d)) == "tmp" and not os.path.exists(gi):
            with open(gi, "w", encoding="utf-8") as f:
                f.write("*\n")
    return d


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def pil():
    try:
        from PIL import Image  # noqa: F401
        return Image
    except ImportError:
        die("Pillow is required: pip install pillow")


def fitz_mod():
    try:
        import fitz  # PyMuPDF
        return fitz
    except ImportError:
        return None


def describe(path: str) -> str:
    Image = pil()
    try:
        with Image.open(path) as im:
            w, h = im.size
            fmt, mode = im.format, im.mode
    except Exception as e:  # unreadable / unsupported
        return f"{path}\t?x?\t{os.path.getsize(path)}B\tunreadable: {e.__class__.__name__}"
    return f"{path}\t{w}x{h}\t{os.path.getsize(path)}B\t{fmt}/{mode}"


def stem_out(src: str, suffix: str, outd: str) -> str:
    base = os.path.splitext(os.path.basename(src))[0]
    return os.path.join(outd, f"{base}.{suffix}.png")


def fit(im, max_side: int):
    w, h = im.size
    s = max(w, h)
    if s <= max_side:
        return im
    r = max_side / s
    return im.resize((max(1, round(w * r)), max(1, round(h * r))), pil().LANCZOS)


def parse_pages(spec: str, n: int | None) -> list[int]:
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a_i = int(a) if a else 1
            b_i = int(b) if b else (n or a_i)
            pages.extend(range(a_i, b_i + 1))
        else:
            pages.append(int(part))
    return sorted(set(p for p in pages if p >= 1 and (n is None or p <= n)))


# ---------------------------------------------------------------- list / batch
def expand(inputs: list[str]) -> list[str]:
    found: list[str] = []
    for p in inputs:
        cands = glob.glob(p, recursive=True) if any(c in p for c in "*?[") else [p]
        for c in cands:
            if os.path.isdir(c):
                for root, _, files in os.walk(c):
                    found += [os.path.join(root, f) for f in files]
            elif os.path.isfile(c):
                found.append(c)
    imgs = {os.path.abspath(f) for f in found if os.path.splitext(f)[1].lower() in IMAGE_EXTS}
    return sorted(imgs, key=natural_key)


def cmd_list(a):
    lim = limits(a)
    files = expand(a.paths)
    print(f"COUNT {len(files)}")
    if not a.batch:
        for f in files:
            print(f)
        return
    size = a.batch_size or lim["DEFAULT_BUDGET"]
    if size > lim["HARD_LIMIT"]:
        die(f"batch size {size} exceeds HARD_LIMIT={lim['HARD_LIMIT']}")
    if not files:
        return
    n = math.ceil(len(files) / size)
    base, extra = divmod(len(files), n)  # balanced batches, each <= size
    i = 0
    for b in range(n):
        k = base + (1 if b < extra else 0)
        chunk = files[i:i + k]
        i += k
        print(f"BATCH {b + 1}/{n} ({len(chunk)} images)")
        for f in chunk:
            print(f"  {f}")


def cmd_info(a):
    for f in expand(a.paths) or a.paths:
        print(describe(os.path.abspath(f)))


# ---------------------------------------------------------------- raster ops
def cmd_resize(a):
    Image = pil()
    outd = out_dir(a.out)
    for src in expand(a.paths):
        with Image.open(src) as im:
            im = fit(im.convert("RGB") if im.mode not in ("RGB", "RGBA", "L") else im, a.max_side)
            dst = stem_out(src, f"max{a.max_side}", outd)
            im.save(dst)
        print(describe(dst))


def cmd_crop(a):
    Image = pil()
    outd = out_dir(a.out)
    vals = [float(v) for v in a.box.split(",")]
    if len(vals) != 4:
        die("--box needs x0,y0,x1,y1")
    with Image.open(a.path) as im:
        w, h = im.size
        if a.frac:
            vals = [vals[0] * w, vals[1] * h, vals[2] * w, vals[3] * h]
        x0, y0, x1, y1 = (int(round(v)) for v in vals)
        x0, x1 = sorted((max(0, x0), min(w, x1)))
        y0, y1 = sorted((max(0, y0), min(h, y1)))
        if x1 - x0 < 1 or y1 - y0 < 1:
            die("empty crop box")
        c = im.crop((x0, y0, x1, y1))
        if a.scale and a.scale != 1:
            c = c.resize((round(c.width * a.scale), round(c.height * a.scale)), Image.LANCZOS)
        c = fit(c, a.max_side)
        dst = stem_out(a.path, f"crop{x0}_{y0}_{x1}_{y1}", outd)
        c.save(dst)
    print(describe(dst))


def cmd_tile(a):
    """Split a tall/wide image into N tiles (each tile = 1 image of budget)."""
    Image = pil()
    outd = out_dir(a.out)
    with Image.open(a.path) as im:
        w, h = im.size
        vertical = h >= w
        n = a.n
        ov = a.overlap
        span = h if vertical else w
        step = span / n
        for i in range(n):
            s = max(0, int(i * step) - (ov if i else 0))
            e = min(span, int((i + 1) * step) + (ov if i < n - 1 else 0))
            box = (0, s, w, e) if vertical else (s, 0, e, h)
            t = fit(im.crop(box), a.max_side)
            dst = stem_out(a.path, f"tile{i + 1}of{n}", outd)
            t.save(dst)
            print(describe(dst) + f"\tregion={box}")


# ---------------------------------------------------------------- PDF
def pdf_text_per_page(pdf: str) -> list[str] | None:
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True)
        if r.returncode == 0:
            pages = r.stdout.decode("utf-8", "replace").split("\f")
            if pages and not pages[-1].strip():
                pages = pages[:-1]
            return pages
    fz = fitz_mod()
    if fz:
        with fz.open(pdf) as doc:
            return [p.get_text() for p in doc]
    return None


def pdf_images_per_page(pdf: str) -> dict[int, list[str]] | None:
    res: dict[int, list[str]] = {}
    if shutil.which("pdfimages"):
        r = subprocess.run(["pdfimages", "-list", pdf], capture_output=True)
        if r.returncode == 0:
            for line in r.stdout.decode("utf-8", "replace").splitlines()[2:]:
                cols = line.split()
                if len(cols) >= 5 and cols[0].isdigit():
                    # page num type width height ...
                    if cols[2] in ("smask", "stencil"):
                        continue
                    res.setdefault(int(cols[0]), []).append(f"{cols[3]}x{cols[4]}")
            return res
    fz = fitz_mod()
    if fz:
        with fz.open(pdf) as doc:
            for i, p in enumerate(doc, 1):
                for img in p.get_images(full=True):
                    res.setdefault(i, []).append(f"{img[2]}x{img[3]}")
        return res
    return None


def pdf_drawings_per_page(pdf: str) -> dict[int, int] | None:
    fz = fitz_mod()
    if not fz:
        return None
    with fz.open(pdf) as doc:
        return {i: len(p.get_drawings()) for i, p in enumerate(doc, 1)}


def cmd_pdf_scan(a):
    pdf = os.path.abspath(a.pdf)
    texts = pdf_text_per_page(pdf)
    imgs = pdf_images_per_page(pdf)
    draws = pdf_drawings_per_page(pdf)
    if texts is None and imgs is None:
        die("need poppler (pdftotext/pdfimages) or PyMuPDF (pip install pymupdf)")
    n = len(texts) if texts is not None else (max(imgs) if imgs else 0)
    print(f"PDF {pdf}\tpages={n}")
    print("page\ttext_chars\timages\tvector_ops\tflag")
    flagged = []
    for p in range(1, n + 1):
        tc = len((texts[p - 1] if texts and p <= len(texts) else "").strip())
        im = imgs.get(p, []) if imgs is not None else []
        big = [s for s in im if all(int(x) >= a.min_px for x in s.split("x"))]
        dv = draws.get(p, 0) if draws else None
        flag = []
        if big:
            flag.append("FIGURE" if tc >= a.scan_chars else "SCAN?")
        if dv is not None and dv >= a.min_vector:
            flag.append("VECTOR_GRAPHICS")
        if flag:
            flagged.append(p)
        print(f"{p}\t{tc}\t{','.join(im) or '-'}\t{'-' if dv is None else dv}\t{'+'.join(flag) or '-'}")
    print(f"VISUAL_PAGES {','.join(map(str, flagged)) or 'none'}")
    if draws is None:
        print("NOTE vector charts are not detected without PyMuPDF; check pdftotext output for 'Figure'/'Chart' captions.")


def cmd_pdf_text(a):
    texts = pdf_text_per_page(os.path.abspath(a.pdf))
    if texts is None:
        die("need poppler or PyMuPDF")
    sel = parse_pages(a.pages, len(texts)) if a.pages else range(1, len(texts) + 1)
    for p in sel:
        print(f"=== page {p} ===")
        print(texts[p - 1].rstrip())


def cmd_pdf_render(a):
    pdf = os.path.abspath(a.pdf)
    outd = out_dir(a.out)
    base = os.path.splitext(os.path.basename(pdf))[0]
    texts = pdf_text_per_page(pdf)
    pages = parse_pages(a.pages, len(texts) if texts else None)
    if not pages:
        die("no valid pages selected")
    Image = pil()
    use_poppler = shutil.which("pdftoppm") is not None
    fz = None if use_poppler else fitz_mod()
    if not use_poppler and not fz:
        die("need poppler (pdftoppm) or PyMuPDF (pip install pymupdf)")
    for p in pages:
        prefix = os.path.join(outd, f"{base}.p{p}")
        dst = prefix + ".png"
        if use_poppler:
            r = subprocess.run(["pdftoppm", "-png", "-r", str(a.dpi), "-f", str(p), "-l", str(p),
                                "-singlefile", pdf, prefix], capture_output=True)
            if r.returncode != 0:
                print(f"FAILED page {p}: {r.stderr.decode(errors='replace').strip()}")
                continue
        else:
            with fz.open(pdf) as doc:
                doc[p - 1].get_pixmap(dpi=a.dpi).save(dst)
        with Image.open(dst) as im:
            im.load()
            small = fit(im, a.max_side)
        if small is not im:
            small.save(dst)
        print(describe(dst) + f"\tpage={p}")


# ---------------------------------------------------------------- screenshot
def cmd_shot(a):
    dst = os.path.abspath(a.out or os.path.join(out_dir(None), f"shot-{int(time.time() * 1000)}.png"))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    done = False
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": a.width, "height": a.height})
            pg.goto(a.url, wait_until="networkidle" if a.wait_idle else "load")
            if a.wait_ms:
                pg.wait_for_timeout(a.wait_ms)
            if a.selector:
                pg.locator(a.selector).first.screenshot(path=dst)
            else:
                pg.screenshot(path=dst, full_page=a.full_page)
            b.close()
            done = True
    except ImportError:
        pass
    if not done:
        if a.selector:
            die("--selector needs Python playwright (pip install playwright)")
        npx = shutil.which("npx") or shutil.which("npx.cmd")
        if not npx:
            die("need Python playwright or Node npx playwright")
        cmd = [npx, "--yes", "playwright", "screenshot", f"--viewport-size={a.width},{a.height}"]
        if a.full_page:
            cmd.append("--full-page")
        if a.wait_ms:
            cmd.append(f"--wait-for-timeout={a.wait_ms}")
        cmd += [a.url, dst]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode != 0 or not os.path.exists(dst):
            die("playwright screenshot failed: " + r.stderr.decode(errors="replace").strip()[-500:])
    print(describe(dst))
    Image = pil()
    with Image.open(dst) as im:
        if max(im.size) > a.max_side:
            print(f"NOTE long side > {a.max_side}px; use `crop`, `tile` or `resize` before delegating")


# ---------------------------------------------------------------- limits
def cmd_doctor(_a):
    import deps
    print(deps.report())
    if deps.problems():
        sys.exit(1)


def cmd_limits(a):
    lim = limits(a)
    print(f"HARD_LIMIT={lim['HARD_LIMIT']} DEFAULT_BUDGET={lim['DEFAULT_BUDGET']}")


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)

    s = sp.add_parser("list", help="expand files/dirs/globs to sorted absolute image paths; --batch to plan batches")
    s.add_argument("paths", nargs="+")
    s.add_argument("--batch", action="store_true")
    s.add_argument("--batch-size", type=int, help="max images per batch (default DEFAULT_BUDGET)")
    s.add_argument("--hard-limit", type=int, help="override HARD_LIMIT (pass the configured value)")
    s.add_argument("--default-budget", type=int, help="override DEFAULT_BUDGET (pass the configured value)")
    s.set_defaults(fn=cmd_list)

    s = sp.add_parser("info", help="dimensions/size/format (no pixels)")
    s.add_argument("paths", nargs="+")
    s.set_defaults(fn=cmd_info)

    s = sp.add_parser("resize", help="downscale so the long side <= --max-side")
    s.add_argument("paths", nargs="+")
    s.add_argument("--max-side", type=int, default=DEFAULT_MAX_SIDE)
    s.add_argument("--out")
    s.set_defaults(fn=cmd_resize)

    s = sp.add_parser("crop", help="crop a region (pixels, or fractions with --frac), optional upscale")
    s.add_argument("path")
    s.add_argument("--box", required=True, help="x0,y0,x1,y1")
    s.add_argument("--frac", action="store_true", help="box values are 0..1 fractions")
    s.add_argument("--scale", type=float, default=1.0)
    s.add_argument("--max-side", type=int, default=DEFAULT_MAX_SIDE)
    s.add_argument("--out")
    s.set_defaults(fn=cmd_crop)

    s = sp.add_parser("tile", help="split a long image into N tiles along its long axis")
    s.add_argument("path")
    s.add_argument("-n", type=int, default=2)
    s.add_argument("--overlap", type=int, default=40)
    s.add_argument("--max-side", type=int, default=DEFAULT_MAX_SIDE)
    s.add_argument("--out")
    s.set_defaults(fn=cmd_tile)

    s = sp.add_parser("pdf-scan", help="per-page text chars / embedded images / vector ops; lists VISUAL_PAGES")
    s.add_argument("pdf")
    s.add_argument("--min-px", type=int, default=64, help="ignore embedded images smaller than this")
    s.add_argument("--scan-chars", type=int, default=50, help="pages with less text are flagged SCAN?")
    s.add_argument("--min-vector", type=int, default=50, help="vector ops to flag VECTOR_GRAPHICS (PyMuPDF only)")
    s.set_defaults(fn=cmd_pdf_scan)

    s = sp.add_parser("pdf-text", help="extract text per page (pdftotext/PyMuPDF)")
    s.add_argument("pdf")
    s.add_argument("--pages", help="e.g. 1,3-5")
    s.set_defaults(fn=cmd_pdf_text)

    s = sp.add_parser("pdf-render", help="render selected pages to PNG (one file per page)")
    s.add_argument("pdf")
    s.add_argument("--pages", required=True, help="e.g. 2,5-6")
    s.add_argument("--dpi", type=int, default=110)
    s.add_argument("--max-side", type=int, default=DEFAULT_MAX_SIDE)
    s.add_argument("--out")
    s.set_defaults(fn=cmd_pdf_render)

    s = sp.add_parser("shot", help="save a web screenshot to a file via Playwright (never returns pixels)")
    s.add_argument("url")
    s.add_argument("--out")
    s.add_argument("--width", type=int, default=1280)
    s.add_argument("--height", type=int, default=800)
    s.add_argument("--full-page", action="store_true")
    s.add_argument("--selector", help="element screenshot (Python playwright only)")
    s.add_argument("--wait-ms", type=int, default=0)
    s.add_argument("--wait-idle", action="store_true")
    s.add_argument("--max-side", type=int, default=DEFAULT_MAX_SIDE)
    s.set_defaults(fn=cmd_shot)

    s = sp.add_parser("doctor", help="check dependencies (Pillow, poppler/PyMuPDF, Playwright); exit 1 if something is missing")
    s.set_defaults(fn=cmd_doctor)

    s = sp.add_parser("limits", help="print effective HARD_LIMIT / DEFAULT_BUDGET (plugin userConfig defaults)")
    s.set_defaults(fn=cmd_limits)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
