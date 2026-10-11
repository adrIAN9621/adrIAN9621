"""Editare PDF cu PyMuPDF.

Coordonatele din operații sunt în puncte PDF, cu originea în colțul STÂNGA-SUS al
paginii așa cum este afișată (ca în PyMuPDF / ca în imaginea randată de render_page).
Indicii de pagină din operații sunt 0-based; intervalele din split sunt 1-based.
"""
from __future__ import annotations

import base64
import binascii
import glob
import os
import re
import sys

try:
    import pymupdf as fitz  # type: ignore
except ImportError:  # pragma: no cover
    import fitz  # type: ignore

RO_SAMPLE = "ăâîșțĂÂÎȘȚşţŞŢ"
_FONT_NAME = "PdfStudioRo"
_font_cache: dict = {}


# --------------------------------------------------------------------------- utilitare

def _open(pdf: bytes) -> "fitz.Document":
    if not pdf:
        raise ValueError("Fișierul PDF este gol.")
    try:
        doc = fitz.open(stream=pdf, filetype="pdf")
    except Exception as exc:
        raise ValueError(f"Fișierul nu este un PDF valid: {exc}") from exc
    if doc.needs_pass:
        doc.close()
        raise ValueError("Documentul PDF este protejat cu parolă și nu poate fi deschis.")
    return doc


def _page_index(doc, page, label: str = "pagina") -> int:
    try:
        p = int(page)
    except (TypeError, ValueError):
        raise ValueError(f"Număr de pagină invalid: {page!r}.")
    if p < 0:
        p += doc.page_count
    if not 0 <= p < doc.page_count:
        raise ValueError(
            f"Pagina {int(page) + 1} nu există (documentul are {doc.page_count} pagini)."
        )
    return p


def _color(value, default=(0, 0, 0)):
    if value is None or value == "":
        return default
    if isinstance(value, (list, tuple)):
        vals = [float(v) for v in value[:3]]
        if any(v > 1 for v in vals):
            vals = [v / 255 for v in vals]
        return tuple(vals)
    s = str(value).strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", s):
        raise ValueError(f"Culoare invalidă: {value!r} (folosiți formatul #RRGGBB).")
    return tuple(int(s[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _rect(page, rect) -> "fitz.Rect":
    """Dreptunghi din coordonate afișate (stânga-sus) -> coordonate nerotite ale paginii."""
    try:
        r = fitz.Rect(*[float(v) for v in rect])
    except Exception:
        raise ValueError(f"Dreptunghi invalid: {rect!r} (așteptat [x0, y0, x1, y1]).")
    r.normalize()
    if r.is_empty:
        raise ValueError("Dreptunghiul selectat are dimensiune zero.")
    if page.rotation:
        r = r * page.derotation_matrix
        r.normalize()
    return r


def _point(page, x, y) -> "fitz.Point":
    try:
        p = fitz.Point(float(x), float(y))
    except Exception:
        raise ValueError("Coordonate invalide.")
    if page.rotation:
        p = p * page.derotation_matrix
    return p


def _font_candidates() -> list[str]:
    names = ["DejaVuSans.ttf", "arial.ttf", "Arial.ttf", "LiberationSans-Regular.ttf",
             "NotoSans-Regular.ttf", "segoeui.ttf", "calibri.ttf", "verdana.ttf",
             "Verdana.ttf", "FreeSans.ttf", "OpenSans-Regular.ttf"]
    dirs: list[str] = []
    if sys.platform.startswith("win"):
        windir = os.environ.get("WINDIR", r"C:\Windows")
        dirs += [os.path.join(windir, "Fonts")]
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    elif sys.platform == "darwin":
        dirs += ["/System/Library/Fonts/Supplemental", "/Library/Fonts",
                 "/System/Library/Fonts", os.path.expanduser("~/Library/Fonts")]
    else:
        dirs += ["/usr/share/fonts", "/usr/local/share/fonts",
                 os.path.expanduser("~/.fonts"), os.path.expanduser("~/.local/share/fonts")]
    out: list[str] = []
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
    for n in names:
        out.append(os.path.join(here, n))
    for d in dirs:
        for n in names:
            out.append(os.path.join(d, n))
            out += glob.glob(os.path.join(d, "**", n), recursive=True)
    return out


def _has_ro(font) -> bool:
    try:
        return all(font.has_glyph(ord(c)) for c in RO_SAMPLE)
    except Exception:
        return False


def _ro_font() -> dict:
    """Returnează {'buffer': bytes|None, 'name': str, 'font': fitz.Font} cu diacritice românești."""
    if "font" in _font_cache:
        return _font_cache["font"]
    seen = set()
    for path in _font_candidates():
        if path in seen or not os.path.isfile(path):
            continue
        seen.add(path)
        try:
            f = fitz.Font(fontfile=path)
        except Exception:
            continue
        if _has_ro(f):
            with open(path, "rb") as fh:
                buf = fh.read()
            _font_cache["font"] = {"buffer": buf, "font": f}
            return _font_cache["font"]
    for builtin in ("notos", "figo", "cjk"):
        try:
            f = fitz.Font(builtin)
        except Exception:
            continue
        if _has_ro(f):
            _font_cache["font"] = {"buffer": f.buffer, "font": f}
            return _font_cache["font"]
    raise ValueError("Nu a fost găsit niciun font cu diacritice românești pe acest sistem.")


def _insert_text(page, x, y, text: str, size: float, color, baseline: bool = False):
    """Scrie text; (x, y) = colțul stânga-sus al textului (sau linia de bază dacă baseline)."""
    fi = _ro_font()
    page.insert_font(fontname=_FONT_NAME, fontbuffer=fi["buffer"])
    font = fi["font"]
    lines = str(text).replace("\r\n", "\n").split("\n")
    asc = font.ascender if font.ascender else 0.8
    line_h = size * 1.2
    y0 = float(y) if baseline else float(y) + size * asc
    for i, line in enumerate(lines):
        if not line:
            continue
        pt = _point(page, float(x), y0 + i * line_h)
        page.insert_text(pt, line, fontname=_FONT_NAME, fontsize=size,
                         color=color, rotate=page.rotation)


# --------------------------------------------------------------------------- API

def info(pdf: bytes) -> dict:
    if not pdf:
        raise ValueError("Fișierul PDF este gol.")
    try:
        doc = fitz.open(stream=pdf, filetype="pdf")
    except Exception as exc:
        raise ValueError(f"Fișierul nu este un PDF valid: {exc}") from exc
    try:
        encrypted = bool(doc.is_encrypted or doc.needs_pass)
        if doc.needs_pass:
            return {"pages": doc.page_count, "page_sizes": [], "metadata": {},
                    "encrypted": True, "signature_count": 0}
        sizes = [[round(p.rect.width, 2), round(p.rect.height, 2)] for p in doc]
        sig = 0
        for p in doc:
            for w in p.widgets() or []:
                if w.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                    sig += 1
        meta = {k: v for k, v in (doc.metadata or {}).items() if v}
        return {"pages": doc.page_count, "page_sizes": sizes, "metadata": meta,
                "encrypted": encrypted, "signature_count": sig}
    finally:
        doc.close()


def spans(pdf: bytes, page: int) -> dict:
    """Returnează dimensiunea paginii (în puncte) și span-urile de text ale paginii.

    Coordonatele bbox sunt în puncte PDF, cu originea în colțul STÂNGA-SUS
    (așa cum le oferă PyMuPDF `get_text("dict")`). Câte o intrare per span;
    span-urile goale sau formate doar din spații sunt ignorate.
    """
    doc = _open(pdf)
    try:
        p = doc[_page_index(doc, page)]
        rect = p.rect
        out = []
        d = p.get_text("dict")
        for b in d.get("blocks", []):
            for line in b.get("lines", []):
                for s in line.get("spans", []):
                    text = s.get("text", "") or ""
                    if not text.strip():
                        continue
                    ci = int(s.get("color", 0) or 0)
                    col = "#%02x%02x%02x" % ((ci >> 16) & 255, (ci >> 8) & 255, ci & 255)
                    flags = int(s.get("flags", 0) or 0)
                    font = str(s.get("font", "") or "")
                    fl = font.lower()
                    bold = bool(flags & 16) or "bold" in fl or "black" in fl or "heavy" in fl
                    italic = bool(flags & 2) or "italic" in fl or "oblique" in fl
                    bbox = [round(float(v), 2) for v in s.get("bbox", (0, 0, 0, 0))]
                    out.append({
                        "text": text,
                        "bbox": bbox,
                        "size": round(float(s.get("size", 0) or 0), 2),
                        "color": col,
                        "font": font,
                        "bold": bold,
                        "italic": italic,
                    })
        return {"width": round(rect.width, 2), "height": round(rect.height, 2), "spans": out}
    finally:
        doc.close()


def render_page(pdf: bytes, page: int, zoom: float = 1.5) -> bytes:
    doc = _open(pdf)
    try:
        p = doc[_page_index(doc, page)]
        zoom = max(0.1, min(float(zoom or 1.5), 8.0))
        pix = p.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False, annots=True)
        return pix.tobytes("png")
    finally:
        doc.close()


def _decode_image(data: str) -> bytes:
    if not data:
        raise ValueError("Imaginea lipsește.")
    s = str(data).strip()
    if s.startswith("data:"):
        s = s.split(",", 1)[1] if "," in s else ""
    s = re.sub(r"\s+", "", s)
    s += "=" * (-len(s) % 4)
    try:
        raw = base64.b64decode(s, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Imaginea nu este codificată corect (base64).") from exc
    if not raw:
        raise ValueError("Imaginea este goală.")
    return raw


def _span_at(page, rect):
    """Caută span-ul de text care se suprapune cel mai mult cu rect (coordonate nerotite)."""
    best, best_area = None, 0.0
    d = page.get_text("dict", clip=rect + (-2, -2, 2, 2))
    for b in d.get("blocks", []):
        for l in b.get("lines", []):
            for s in l.get("spans", []):
                inter = fitz.Rect(s["bbox"]) & rect
                area = inter.get_area() if not inter.is_empty else 0.0
                if area > best_area:
                    best, best_area = s, area
    return best


def _replace_text(doc, search: str, replace: str, page) -> int:
    if not search:
        raise ValueError("Textul de căutat este gol.")
    pages = [_page_index(doc, page)] if page is not None and page != "" else range(doc.page_count)
    total = 0
    for pno in pages:
        p = doc[pno]
        hits = p.search_for(search)
        if not hits:
            continue
        infos = []
        for r in hits:
            s = _span_at(p, r)
            size = float(s["size"]) if s else max(r.height * 0.8, 4)
            color = s.get("color", 0) if s else 0
            col = tuple(((color >> sh) & 255) / 255 for sh in (16, 8, 0))
            baseline = float(s["origin"][1]) if s else r.y1 - size * 0.2
            infos.append((r, size, col, baseline))
            p.add_redact_annot(r, fill=(1, 1, 1))
        p.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                           graphics=getattr(fitz, "PDF_REDACT_LINE_ART_NONE", 0))
        if replace:
            fi = _ro_font()
            p.insert_font(fontname=_FONT_NAME, fontbuffer=fi["buffer"])
            for r, size, col, baseline in infos:
                p.insert_text(fitz.Point(r.x0, baseline), replace, fontname=_FONT_NAME,
                              fontsize=size, color=col)
        total += len(hits)
    if total == 0:
        raise ValueError(f"Textul „{search}” nu a fost găsit în document.")
    return total


def _move_page(doc, frm, to):
    n = doc.page_count
    f = _page_index(doc, frm)
    try:
        t = int(to)
    except (TypeError, ValueError):
        raise ValueError(f"Poziție invalidă: {to!r}.")
    if t < 0:
        t += n
    if not 0 <= t < n:
        raise ValueError(f"Poziția {t + 1} nu există (documentul are {n} pagini).")
    if f == t:
        return
    if t > f:
        # pagina trebuie să ajungă la indexul final t
        doc.move_page(f, -1 if t == n - 1 else t + 1)
    else:
        doc.move_page(f, t)


def apply_edits(pdf: bytes, ops: list[dict]) -> bytes:
    if not isinstance(ops, list):
        raise ValueError("Lista de operații este invalidă.")
    doc = _open(pdf)
    try:
        for i, op in enumerate(ops):
            if not isinstance(op, dict):
                raise ValueError(f"Operația {i + 1} este invalidă.")
            _apply_op(doc, op)
        return doc.tobytes(garbage=3, deflate=True)
    finally:
        doc.close()


def _apply_op(doc, op: dict):
    t = op.get("type")
    if t == "add_text":
        text = op.get("text") or ""
        if not text.strip():
            raise ValueError("Textul de adăugat este gol.")
        p = doc[_page_index(doc, op.get("page", 0))]
        size = float(op.get("size") or 12)
        _insert_text(p, op.get("x", 0), op.get("y", 0), text, size,
                     _color(op.get("color"), (0, 0, 0)))
    elif t == "highlight":
        p = doc[_page_index(doc, op.get("page", 0))]
        a = p.add_highlight_annot(_rect(p, op.get("rect")))
        if op.get("color"):
            a.set_colors(stroke=_color(op["color"]))
            a.update()
    elif t == "rect":
        p = doc[_page_index(doc, op.get("page", 0))]
        fill = op.get("fill")
        p.draw_rect(_rect(p, op.get("rect")),
                    color=_color(op.get("color"), (1, 0, 0)),
                    fill=_color(fill) if fill else None,
                    width=float(op.get("width") if op.get("width") is not None else 1))
    elif t == "whiteout":
        p = doc[_page_index(doc, op.get("page", 0))]
        p.draw_rect(_rect(p, op.get("rect")), color=None, fill=(1, 1, 1), width=0)
    elif t == "redact":
        p = doc[_page_index(doc, op.get("page", 0))]
        p.add_redact_annot(_rect(p, op.get("rect")), fill=_color(op.get("fill"), (0, 0, 0)))
        p.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)
    elif t == "image":
        p = doc[_page_index(doc, op.get("page", 0))]
        raw = _decode_image(op.get("image_b64"))
        try:
            p.insert_image(_rect(p, op.get("rect")), stream=raw, keep_proportion=True)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"Imaginea nu a putut fi inserată: {exc}") from exc
    elif t == "edit_text":
        p = doc[_page_index(doc, op.get("page", 0))]
        raw = op.get("rect")
        rr = _rect(p, raw)  # dreptunghi nerotit, pentru redactare
        text = str(op.get("text") if op.get("text") is not None else "")
        color = _color(op.get("color"), (0, 0, 0))
        # elimină glifele originale din zonă
        p.add_redact_annot(rr, fill=(1, 1, 1))
        p.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                           graphics=getattr(fitz, "PDF_REDACT_LINE_ART_NONE", 0))
        if text.strip():
            disp = fitz.Rect(*[float(v) for v in raw])
            disp.normalize()
            fi = _ro_font()
            font = fi["font"]
            try:
                size = float(op.get("size") or 0)
            except (TypeError, ValueError):
                size = 0
            if size <= 0:
                size = max(disp.height * 0.8, 4)
            if disp.height > 0 and size > disp.height:
                size = disp.height
            # micșorează dacă textul ar depăși lățimea dreptunghiului
            try:
                tl = font.text_length(text, fontsize=size)
                if disp.width > 0 and tl > disp.width and tl > 0:
                    size = max(4.0, size * disp.width / tl)
            except Exception:
                pass
            _insert_text(p, disp.x0, disp.y0, text, size, color)
    elif t == "replace_text":
        _replace_text(doc, op.get("search") or "", op.get("replace") or "", op.get("page"))
    elif t == "rotate":
        try:
            angle = int(op.get("angle", 90))
        except (TypeError, ValueError):
            raise ValueError("Unghi de rotire invalid.")
        if angle % 90:
            raise ValueError("Unghiul de rotire trebuie să fie multiplu de 90°.")
        page = op.get("page")
        pages = range(doc.page_count) if page is None or page == "all" else [_page_index(doc, page)]
        for pno in pages:
            p = doc[pno]
            p.set_rotation((p.rotation + angle) % 360)
    elif t == "delete_page":
        if doc.page_count <= 1:
            raise ValueError("Nu se poate șterge singura pagină a documentului.")
        doc.delete_page(_page_index(doc, op.get("page")))
    elif t == "move_page":
        _move_page(doc, op.get("from"), op.get("to"))
    elif t == "insert_blank":
        at = op.get("at", doc.page_count)
        at = doc.page_count if at is None else int(at)
        if not 0 <= at <= doc.page_count:
            raise ValueError(f"Poziție invalidă pentru pagina nouă: {at + 1}.")
        ref = doc[min(at, doc.page_count - 1)] if doc.page_count else None
        w = op.get("width") or (ref.rect.width if ref else 595)
        h = op.get("height") or (ref.rect.height if ref else 842)
        doc.new_page(pno=at if at < doc.page_count else -1, width=w, height=h)
    elif t == "note":
        text = op.get("text") or ""
        p = doc[_page_index(doc, op.get("page", 0))]
        a = p.add_text_annot(_point(p, op.get("x", 0), op.get("y", 0)), text)
        a.update()
    elif t == "set_metadata":
        meta = dict(doc.metadata or {})
        for k in ("title", "author", "subject", "keywords", "creator", "producer"):
            if k in op and op[k] is not None:
                meta[k] = str(op[k])
        doc.set_metadata({k: v for k, v in meta.items() if k in (
            "title", "author", "subject", "keywords", "creator", "producer",
            "creationDate", "modDate", "trapped") and v is not None})
    else:
        raise ValueError(f"Operație necunoscută: {t!r}.")


def merge(pdfs: list[bytes]) -> bytes:
    if not pdfs:
        raise ValueError("Nu a fost selectat niciun PDF pentru unire.")
    out = fitz.open()
    try:
        for i, data in enumerate(pdfs):
            try:
                src = _open(data)
            except ValueError as exc:
                raise ValueError(f"Fișierul {i + 1}: {exc}") from exc
            try:
                out.insert_pdf(src)
            finally:
                src.close()
        return out.tobytes(garbage=3, deflate=True)
    finally:
        out.close()


def _parse_ranges(ranges: str, n: int) -> list[tuple[int, int]]:
    if not ranges or not str(ranges).strip():
        raise ValueError("Intervalele de pagini lipsesc (ex.: 1-3,4,5-end).")

    def num(tok: str) -> int:
        tok = tok.strip().lower()
        if tok in ("end", "sfarsit", "sfârșit", "ultima", "$"):
            return n
        if not tok.isdigit():
            raise ValueError(f"Interval invalid: „{tok}” (ex.: 1-3,4,5-end).")
        return int(tok)

    out = []
    for part in re.split(r"[,;]", str(ranges)):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            s, e = num(a), num(b)
        else:
            s = e = num(part)
        if s < 1 or e < 1 or s > n or e > n:
            raise ValueError(f"Intervalul „{part}” depășește numărul de pagini ({n}).")
        if s > e:
            raise ValueError(f"Intervalul „{part}” este inversat.")
        out.append((s, e))
    if not out:
        raise ValueError("Nu a fost specificat niciun interval valid.")
    return out


def split(pdf: bytes, ranges: str) -> list[bytes]:
    doc = _open(pdf)
    try:
        result = []
        for s, e in _parse_ranges(ranges, doc.page_count):
            part = fitz.open()
            try:
                part.insert_pdf(doc, from_page=s - 1, to_page=e - 1)
                result.append(part.tobytes(garbage=3, deflate=True))
            finally:
                part.close()
        return result
    finally:
        doc.close()


def extract_text(pdf: bytes) -> str:
    doc = _open(pdf)
    try:
        parts = []
        for i, p in enumerate(doc):
            parts.append(f"--- Pagina {i + 1} ---\n{p.get_text('text').rstrip()}")
        return "\n\n".join(parts)
    finally:
        doc.close()


def compress(pdf: bytes) -> bytes:
    doc = _open(pdf)
    try:
        kw = dict(garbage=4, deflate=True, clean=True,
                  deflate_images=True, deflate_fonts=True)
        try:
            out = doc.tobytes(use_objstms=1, **kw)
        except TypeError:
            out = doc.tobytes(**kw)
    finally:
        doc.close()
    return out if len(out) < len(pdf) else pdf
