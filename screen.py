"""Defense layer 1 (code): screen every vendor document before any model sees it, and check the answer after.

Input side (before the model):
- Rebuild the document the way a person sees it: browser-visible HTML, the text a PDF viewer actually draws,
  the email part an email app displays. Anything a person cannot see is cut out and reported with where it was hidden.
  This is structural, not a keyword list:
    HTML  inline styles AND the page's own <style> rules (tags, classes, ids, attributes, nested selectors), computed
          font size, text colour against its actual background (contrast), display/visibility/opacity, off-screen
          and zero-size boxes, clipping, transforms, collapsed <details>, comments, page code, attribute text; text
          the stylesheet DRAWS (::before/::after content) is added, because a person sees it.
    PDF   white or tiny text, invisible render modes, text off the page or outside the clip area, and text painted
          over by an image or filled shape drawn later.
    Email the part an email app displays (HTML when present), plus a warning if the hidden plain-text twin disagrees.
- Flag words that mix look-alike letters from different alphabets (vendor impersonation).
- Normalise Unicode (NFKC) and strip zero-width / direction-control characters used to dodge filters.
- Neutralise web links so they cannot be copied into an answer (exfiltration and phishing links).
- Cap the length (cost and denial-of-service protection).
- Scan both the visible and the hidden text for instruction-like content. This is a secondary signal for the
  human-review flag only; it never changes a fact or a decision on its own.

Output side (after the model):
- Fact check: every fact in the answer must appear in what a person sees. A fact that only existed in hidden text
  cannot survive, even if the model believed it.
- Scrub links, email addresses and invisible characters out of the answer.
"""

from __future__ import annotations

import email
import re
import unicodedata
from dataclasses import dataclass, field
from email import policy
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.generic import ContentStream

MAX_MODEL_CHARS = 8_000  # far above any real quote here (largest visible doc is under 600 characters)

# ---------------------------------------------------------------------------------------------
# What a person sees: HTML (inline styles AND <style> rules, computed like a browser)
# ---------------------------------------------------------------------------------------------

NON_RENDERED = {"script", "style", "head", "title", "template", "noscript", "meta", "object", "iframe"}
PAGE_CODE = {"script", "style", "head", "title", "meta"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
BLOCK_TAGS = {"p", "div", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "li", "header", "footer", "section", "table",
              "article", "blockquote", "pre", "ul", "ol", "dl", "dt", "dd", "address", "main", "nav", "aside",
              "details", "summary"}
TEXT_ATTRS = {"alt", "title", "aria-label", "aria-description", "placeholder", "value", "content", "label"}
SHOWN = "__shown__"  # a <summary> stays visible inside a collapsed <details>
DEFAULT_TEXT = (0, 0, 0, 1.0)
DEFAULT_BG = (255, 255, 255, 1.0)
MIN_READABLE_PX = 4.0
MIN_CONTRAST = 1.25  # WCAG ratio; black on white is 21, #fefefe on white is 1.01

NAMED_COLORS = {
    "white": (255, 255, 255), "black": (0, 0, 0), "red": (255, 0, 0), "green": (0, 128, 0), "blue": (0, 0, 255),
    "gray": (128, 128, 128), "grey": (128, 128, 128), "silver": (192, 192, 192), "whitesmoke": (245, 245, 245),
    "snow": (255, 250, 250), "ivory": (255, 255, 240), "ghostwhite": (248, 248, 255), "navy": (0, 0, 128),
    "floralwhite": (255, 250, 240), "mintcream": (245, 255, 250), "azure": (240, 255, 255), "linen": (250, 240, 230),
}


def parse_color(value: str | None) -> tuple[float, float, float, float] | None:
    if not value:
        return None
    v = value.lower().replace("!important", "").strip()
    if v == "transparent":
        return (0, 0, 0, 0.0)
    if v in NAMED_COLORS:
        return (*NAMED_COLORS[v], 1.0)
    m = re.fullmatch(r"#([0-9a-f]{3,8})", v)
    if m and len(m.group(1)) in (3, 4, 6, 8):
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        alpha = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)
    m = re.fullmatch(r"rgba?\(([^)]*)\)", v)
    if m:
        parts = [p for p in re.split(r"[\s,/]+", m.group(1).strip()) if p]
        try:
            rgb = [float(p[:-1]) * 2.55 if p.endswith("%") else float(p) for p in parts[:3]]
            alpha = float(parts[3][:-1]) / 100 if len(parts) > 3 and parts[3].endswith("%") else (float(parts[3]) if len(parts) > 3 else 1.0)
            return (*rgb, alpha)
        except (ValueError, IndexError):
            return None
    return None


def _background(decls: dict[str, str]) -> tuple[float, float, float, float] | None:
    if "background-color" in decls:
        return parse_color(decls["background-color"])
    for token in re.split(r"\s+(?![^(]*\))", decls.get("background", "")):
        c = parse_color(token)
        if c:
            return c
    return None


def _luminance(c: tuple[float, ...]) -> float:
    def ch(v: float) -> float:
        v = max(0.0, min(255.0, v)) / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def contrast(fg: tuple[float, ...], bg: tuple[float, ...]) -> float:
    a, b = _luminance(fg), _luminance(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def font_px(value: str | None, parent: float) -> float | None:
    if not value:
        return None
    v = value.lower().replace("!important", "").strip()
    keywords = {"xx-small": 9, "x-small": 10, "small": 13, "medium": 16, "large": 18, "x-large": 24, "xx-large": 32}
    if v in keywords:
        return float(keywords[v])
    if v == "smaller":
        return parent * 0.83
    if v == "larger":
        return parent * 1.2
    m = re.fullmatch(r"(-?\d*\.?\d+)\s*(px|pt|em|rem|%|vw|vh|vmin|vmax|ex|ch)?", v)
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2)
    factor = {"px": 1, "pt": 4 / 3, "em": parent, "rem": 16, "%": parent / 100, "vw": 12.8, "vh": 8, "vmin": 8,
              "vmax": 12.8, "ex": parent / 2, "ch": parent / 2}
    if unit is None:
        return 0.0 if n == 0 else None
    return n * factor[unit]


def _num_px(value: str) -> float | None:
    m = re.match(r"\s*(-?\d*\.?\d+)\s*(px|pt|em|rem|%|vw|vh)?", value or "")
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2) or "px"
    return n * {"px": 1, "pt": 4 / 3, "em": 16, "rem": 16, "%": 1, "vw": 12.8, "vh": 8}[unit]


def structural_hiding(decls: dict[str, str]) -> list[str]:
    """Reasons a box and everything in it is not visible, from its CSS declarations."""
    d = {k: v.lower() for k, v in decls.items()}
    why = []
    if d.get("display", "").startswith("none"):
        why.append("CSS display:none")
    if d.get("visibility", "").startswith(("hidden", "collapse")):
        why.append("CSS visibility:hidden")
    try:
        if "opacity" in d and float(d["opacity"].replace("!important", "").strip().rstrip("%")) < 0.05:
            why.append("CSS opacity 0")
    except ValueError:
        pass
    for prop in ("left", "top", "right", "bottom", "margin-left", "margin-top", "text-indent", "translate"):
        n = _num_px(d.get(prop, ""))
        if n is not None and n <= -500:
            why.append(f"moved off-screen ({prop}: {d[prop]})")
            break
    if re.search(r"translate[xy]?\(\s*-\s*\d{3,}", d.get("transform", "")) or re.search(r"scale[xy]?\(\s*0(?:\.0+)?\s*[,)]", d.get("transform", "")):
        why.append("moved or shrunk away with CSS transform")
    overflow = " ".join(d.get(k, "") for k in ("overflow", "overflow-x", "overflow-y"))
    if "hidden" in overflow or "clip" in overflow:
        for prop in ("height", "width", "max-height", "max-width"):
            n = _num_px(d.get(prop, ""))
            if n is not None and n <= 1:
                why.append(f"zero-size box ({prop}: {d[prop]}, overflow hidden)")
                break
    if re.search(r"rect\(\s*0|inset\(\s*50%|circle\(\s*0", d.get("clip", "") + " " + d.get("clip-path", "")):
        why.append("clipped away (CSS clip)")
    return why


# --- a small CSS engine: enough selectors to apply a page's own <style> rules -----------------

_CSS_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_DECL = re.compile(r"([\w-]+)\s*:\s*((?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^;])+)")
_COMPOUND = re.compile(r"^(\*|[a-zA-Z][\w-]*)?((?:\.[\w-]+|#[\w-]+|\[[^\]]+\])*)$")


def parse_decls(text: str) -> dict[str, str]:
    return {k.lower(): v.strip() for k, v in _DECL.findall(text or "")}


def css_unescape(s: str) -> str:
    return re.sub(r"\\([0-9a-fA-F]{1,6})\s?|\\(.)", lambda m: chr(int(m.group(1), 16)) if m.group(1) else m.group(2), s)


def _parse_selector(sel: str):
    sel = sel.strip()
    pseudo = None
    m = re.search(r"::?(before|after)\s*$", sel, re.I)
    if m:
        pseudo, sel = m.group(1).lower(), sel[: m.start()]
    if ":" in sel or not sel:
        return None  # :hover and friends can't be judged statically; skip the rule
    sel = re.sub(r"\s*([>+~])\s*", r" \1 ", sel)
    compounds = []
    for part in sel.split():
        if part in ("+", "~"):
            return None
        if part == ">":
            continue  # treated as "descendant": slightly broader, never narrower
        m = _COMPOUND.match(part)
        if not m:
            return None
        rest = m.group(2)
        attrs = []
        for a in re.findall(r"\[([^\]]+)\]", rest):
            am = re.match(r"\s*([\w-]+)\s*(?:([~|^$*]?=)\s*[\"']?([^\"']*)[\"']?)?\s*$", a)
            if not am:
                return None
            attrs.append((am.group(1).lower(), am.group(2), am.group(3)))
        tag = m.group(1)
        compounds.append(((tag.lower() if tag and tag != "*" else None), re.findall(r"#([\w-]+)", rest),
                          re.findall(r"\.([\w-]+)", rest), attrs))
    spec = (sum(len(c[1]) for c in compounds), sum(len(c[2]) + len(c[3]) for c in compounds),
            sum(1 for c in compounds if c[0]))
    return compounds, pseudo, spec


def parse_css(text: str) -> list[tuple]:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    rules = []
    for order, m in enumerate(_CSS_RULE.finditer(text)):
        selectors = m.group(1).strip()
        if selectors.startswith("@"):
            continue  # @font-face, @page ...
        decls = parse_decls(m.group(2))
        for sel in selectors.split(","):
            parsed = _parse_selector(sel)
            if parsed:
                compounds, pseudo, spec = parsed
                rules.append((spec, order, compounds, pseudo, decls))
    rules.sort(key=lambda r: (r[0], r[1]))
    return rules


def _compound_matches(c, el: dict[str, Any]) -> bool:
    tag, ids, classes, attrs = c
    if tag and tag != el["tag"]:
        return False
    if any(i != el["id"] for i in ids) or not set(classes) <= el["classes"]:
        return False
    for name, op, val in attrs:
        have = el["attrs"].get(name)
        if have is None:
            return False
        have = have or ""
        if op == "=" and have != val or op == "~=" and val not in have.split() or op == "*=" and val not in have \
                or op == "^=" and not have.startswith(val) or op == "$=" and not have.endswith(val) \
                or op == "|=" and not (have == val or have.startswith(val + "-")):
            return False
    return True


def _selector_matches(compounds, el: dict[str, Any], ancestors: list[dict[str, Any]]) -> bool:
    if not _compound_matches(compounds[-1], el):
        return False
    i = len(ancestors) - 1
    for c in reversed(compounds[:-1]):
        while i >= 0 and not _compound_matches(c, ancestors[i]):
            i -= 1
        if i < 0:
            return False
        i -= 1
    return True


def css_content(value: str | None, attrs: dict[str, str | None]) -> str:
    """Text a ::before/::after rule draws on screen (strings and attr() values)."""
    if not value or value.strip().lower() in ("none", "normal", "''", '""'):
        return ""
    parts = []
    for dq, sq, attr in re.findall(r"\"((?:\\.|[^\"\\])*)\"|'((?:\\.|[^'\\])*)'|attr\(\s*([\w-]+)\s*\)", value):
        parts.append(attrs.get(attr.lower()) or "" if attr else css_unescape(dq or sq))
    text = " ".join("".join(parts).split())
    return text if re.search(r"\w", text) else ""


class _VisibleText(HTMLParser):
    """Split an HTML page into what a browser shows and what it hides (with the reason it is hidden)."""

    def __init__(self, rules: list[tuple]) -> None:
        super().__init__(convert_charrefs=True)
        self.rules = rules
        self.out: list[str] = []
        self.hidden: list[dict[str, str]] = []
        self.stack: list[dict[str, Any]] = []

    def _parent(self) -> dict[str, Any]:
        return self.stack[-1] if self.stack else {"tag": "", "reason": None, "font": 16.0, "color": DEFAULT_TEXT,
                                                  "bg": DEFAULT_BG, "after": None, "info": None}

    def _chain_reason(self) -> str | None:
        for e in reversed(self.stack):
            if e["reason"] == SHOWN:
                return None
            if e["reason"]:
                return e["reason"]
        return None

    def _render_reason(self, font: float, color: tuple, bg: tuple) -> str | None:
        why = []
        if font < MIN_READABLE_PX:
            why.append(f"font-size {font:g}px")
        if color[3] < 0.1:
            why.append("transparent text")
        elif contrast(color, bg) < MIN_CONTRAST:
            why.append(f"text colour matches its background (contrast {contrast(color, bg):.2f}:1)")
        return " + ".join(why) or None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): v for k, v in attrs}
        for k, v in a.items():  # text tucked into attributes is never drawn as page text
            if v and (k in TEXT_ATTRS or k.startswith("data-")) and len(v.strip()) >= 12 and tag != "meta" or \
                    (tag == "meta" and k == "content" and v and len(v) >= 40):
                self.hidden.append({"where": f"HTML attribute <{tag} {k}=...> (not shown as page text)", "text": " ".join(v.split())})
        if tag == "br":
            self.out.append("\n")
        if tag in VOID_TAGS:
            return
        if tag in BLOCK_TAGS:
            self.out.append("\n")
        elif tag in ("td", "th"):
            self.out.append(" | ")
        parent = self._parent()
        el = {"tag": tag, "id": a.get("id"), "classes": set((a.get("class") or "").split()), "attrs": a}
        ancestors = [e["info"] for e in self.stack]
        decls: dict[str, str] = {}
        pseudo: dict[str, dict[str, str]] = {"before": {}, "after": {}}
        for _, _, compounds, which, d in self.rules:
            if _selector_matches(compounds, el, ancestors):
                (pseudo[which] if which else decls).update(d)
        decls.update(parse_decls(a.get("style") or ""))

        font = font_px(decls.get("font-size"), parent["font"])
        font = parent["font"] if font is None else font
        color = parse_color(decls.get("color")) or parent["color"]
        own_bg = _background(decls)
        bg = own_bg if own_bg and own_bg[3] > 0.5 else parent["bg"]

        reasons = structural_hiding(decls)
        if "hidden" in a:
            reasons.append("HTML hidden attribute")
        if tag in NON_RENDERED:
            reasons.append(f"<{tag}> element (page code, not shown)" if tag in PAGE_CODE else f"<{tag}> element (not shown)")
        if tag == "details" and "open" not in a:
            reasons.append("collapsed <details> section (not opened)")
        reason = " + ".join(reasons) or (SHOWN if tag == "summary" and parent["tag"] == "details" else None)
        entry = {"tag": tag, "reason": reason, "font": font, "color": color, "bg": bg, "after": None, "info": el}
        self.stack.append(entry)

        for which in ("before", "after"):
            text = css_content(pseudo[which].get("content"), a)
            if not text:
                continue
            pd = pseudo[which]
            pfont = font_px(pd.get("font-size"), font)
            pfont = font if pfont is None else pfont
            pcolor = parse_color(pd.get("color")) or color
            hide = " + ".join(structural_hiding(pd)) or self._chain_reason() or self._render_reason(pfont, pcolor, bg)
            if hide:
                self.hidden.append({"where": f"CSS ::{which} text on <{tag}>, itself hidden ({hide})", "text": text})
                continue
            self.hidden.append({"where": f"CSS ::{which} text drawn on screen but not in the page text", "text": text,
                                "shown": "yes"})
            if which == "before":
                self.out.append(text)
            else:
                entry["after"] = text

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS:
            return
        for i in range(len(self.stack) - 1, -1, -1):  # tolerate unclosed tags
            if self.stack[i]["tag"] == tag:
                for e in reversed(self.stack[i:]):
                    if e["after"]:
                        self.out.append(e["after"])
                del self.stack[i:]
                break
        if tag in BLOCK_TAGS:
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        if not data.strip():
            return
        text = " ".join(data.split())
        top = self._parent()
        reason = self._chain_reason() or self._render_reason(top["font"], top["color"], top["bg"])
        if reason:
            self.hidden.append({"where": reason, "text": text})
        else:
            self.out.append(text)

    def handle_comment(self, data: str) -> None:
        if data.strip():
            self.hidden.append({"where": "HTML comment <!-- -->", "text": " ".join(data.split())})


def _tidy(chunks: list[str]) -> str:
    text = "".join(c if c in ("\n", " | ") else f" {c} " for c in chunks)
    lines = [" ".join(line.split()).strip(" |") for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def html_view(html: str) -> tuple[str, list[dict[str, str]]]:
    css = " ".join(re.findall(r"<style[^>]*>(.*?)</style\s*>", html, re.S | re.I))
    p = _VisibleText(parse_css(css))
    p.feed(html)
    p.close()
    return _tidy(p.out), p.hidden


# ---------------------------------------------------------------------------------------------
# What a person sees: PDF (colour, size, position, clipping, and anything painted on top)
# ---------------------------------------------------------------------------------------------

IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
FILL_OPS = {"f", "F", "f*", "B", "B*", "b", "b*"}


def _mat(m: tuple, n: tuple) -> tuple:
    """m x n for PDF affine matrices (a b c d e f): apply m first, then n."""
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2, c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


def _pt(m: tuple, x: float, y: float) -> tuple[float, float]:
    return m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]


def _box(m: tuple, x: float, y: float, w: float, h: float) -> tuple[float, float, float, float]:
    pts = [_pt(m, px, py) for px, py in ((x, y), (x + w, y), (x, y + h), (x + w, y + h))]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _inside(px: float, py: float, r: tuple[float, float, float, float]) -> bool:
    return r[0] - 0.5 <= px <= r[2] + 0.5 and r[1] - 0.5 <= py <= r[3] + 0.5


def _pdf_view(path: Path) -> tuple[str, list[dict[str, str]]]:
    """A PDF viewer shows text that is on the page, inside the clip area, not white, big enough to read, not in an
    invisible render mode, and not painted over by an image or filled shape drawn later."""
    visible, hidden = [], []
    for page in PdfReader(path).pages:
        x0, y0, x1, y1 = (float(v) for v in page.mediabox)
        res = page.get("/Resources") or {}
        xobjects = res.get("/XObject") or {}
        texts, paints = [], []  # (index, ...) so we know what was drawn after what
        ctm, fill, clip = IDENTITY, (0.0, 0.0, 0.0), None
        stack: list[tuple] = []
        size, scale, line, render = 12.0, 1.0, [0.0, 0.0], 0
        pending: list[tuple] = []
        clip_next = False
        for idx, (ops, op) in enumerate(ContentStream(page.get_contents(), page.pdf).operations):
            op = op.decode() if isinstance(op, bytes) else op
            if op == "q":
                stack.append((ctm, fill, clip))
            elif op == "Q" and stack:
                ctm, fill, clip = stack.pop()
            elif op == "cm":
                ctm = _mat(tuple(float(o) for o in ops), ctm)
            elif op == "rg":
                fill = tuple(float(o) for o in ops)
            elif op == "g":
                fill = (float(ops[0]),) * 3
            elif op == "k":  # CMYK: all zero = white
                c, m, y, k = (float(o) for o in ops)
                fill = tuple((1 - min(1.0, v + k)) for v in (c, m, y))
            elif op == "re":
                x, y, w, h = (float(o) for o in ops)
                pending.append(_box(ctm, x, y, w, h))
            elif op in ("W", "W*"):
                clip_next = True
            elif op in FILL_OPS or op in ("n", "S", "s"):
                if clip_next and pending:
                    r = (min(p[0] for p in pending), min(p[1] for p in pending), max(p[2] for p in pending), max(p[3] for p in pending))
                    clip = r if clip is None else (max(clip[0], r[0]), max(clip[1], r[1]), min(clip[2], r[2]), min(clip[3], r[3]))
                if op in FILL_OPS:
                    paints.extend((idx, "a filled shape", r) for r in pending)
                pending, clip_next = [], False
            elif op == "Do":
                xo = xobjects.get(ops[0])
                xo = xo.get_object() if xo is not None else None
                if xo is not None and xo.get("/Subtype") == "/Image" and "/SMask" not in xo and "/Mask" not in xo \
                        and not xo.get("/ImageMask"):
                    paints.append((idx, "an image", _box(ctm, 0, 0, 1, 1)))
            elif op == "INLINE IMAGE":
                paints.append((idx, "an image", _box(ctm, 0, 0, 1, 1)))
            elif op == "BT":
                line, scale = [0.0, 0.0], 1.0
            elif op == "Tf":
                size = float(ops[1])
            elif op == "Tm":
                scale = abs(float(ops[3])) or abs(float(ops[0])) or 1.0
                line = [float(ops[4]), float(ops[5])]
            elif op in ("Td", "TD"):
                line = [line[0] + float(ops[0]), line[1] + float(ops[1])]
            elif op == "Tr":
                render = int(ops[0])
            elif op in ("Tj", "TJ", "'", '"'):
                raw = ops[-1] if op != "TJ" else "".join(str(x) for x in ops[0] if isinstance(x, (str, bytes)))
                text = " ".join(str(raw).split())
                if not text:
                    continue
                px, py = _pt(ctm, *line)
                eff = size * scale * (abs(ctm[3]) or abs(ctm[0]) or 1.0)
                why = None
                if render in (3, 7):
                    why = "invisible text render mode"
                elif min(fill) > 0.95:
                    why = f"white text (fill {fill[0]:g} {fill[1]:g} {fill[2]:g}) on a white page"
                elif eff < 4:
                    why = f"tiny text ({eff:g} pt) at x={px:g}, y={py:g}"
                elif not (x0 <= px <= x1 and y0 <= py <= y1):
                    why = f"placed off the page (x={px:g}, y={py:g}; page is {x1 - x0:g}x{y1 - y0:g})"
                elif clip is not None and not _inside(px, py, clip):
                    why = f"clipped out of view (x={px:g}, y={py:g})"
                width = len(text) * eff * 0.5
                texts.append({"idx": idx, "text": text, "why": why, "pts": [(px, py + eff * 0.3), (px + width / 2, py + eff * 0.3)]})
        for t in texts:
            if not t["why"]:
                cover = next((what for i, what, r in paints if i > t["idx"] and all(_inside(*p, r) for p in t["pts"])), None)
                if cover:
                    t["why"] = f"covered by {cover} drawn on top of it"
            (hidden.append({"where": t["why"], "text": t["text"]}) if t["why"] else visible.append(t["text"]))
    return "\n".join(visible), hidden


# ---------------------------------------------------------------------------------------------
# What a person sees: email
# ---------------------------------------------------------------------------------------------

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _eml_view(path: Path) -> tuple[str, list[dict[str, str]]]:
    """An email app shows the headers plus the HTML part when there is one, otherwise the plain-text part."""
    msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    header = "\n".join(f"{h}: {msg[h]}" for h in ("From", "To", "Subject", "Date") if msg[h])
    html_part = msg.get_body(preferencelist=("html",))
    plain_part = msg.get_body(preferencelist=("plain",))
    if html_part is None:
        return f"{header}\n{plain_part.get_content().strip() if plain_part else ''}", []
    visible, hidden = html_view(html_part.get_content())
    if plain_part is not None:  # the plain-text twin is never displayed when an HTML part exists
        plain = plain_part.get_content()
        if sorted(_NUM_RE.findall(plain)) != sorted(_NUM_RE.findall(visible)):
            hidden.insert(0, {"where": "text/plain alternative that disagrees with the HTML a person sees",
                              "text": " ".join(plain.split())[:300]})
    return f"{header}\n{visible}", hidden


def human_view(path: Path) -> tuple[str, list[dict[str, str]]]:
    """(text a person sees, list of hidden pieces with where each was hidden)."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _pdf_view(path)
    if suffix == ".eml":
        return _eml_view(path)
    return html_view(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------
# Cleaning and scanning
# ---------------------------------------------------------------------------------------------

INVISIBLE_RE = re.compile(r"[​-‏‪-‮⁠-⁩﻿­᠎]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
LINK_RE = re.compile(r"https?://\S+|www\.\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)+/\S*", re.I)
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")

# Secondary signal only (never changes a fact or decision). Each pattern names a known attack move.
INJECTION_PATTERNS = (
    (r"\bignore\b.{0,40}\b(?:instruction|rule|prompt|previous|prior|above|system)", "tells the reader to ignore its instructions", "any"),
    (r"\b(?:system|developer)\s*(?:override|prompt|message|instruction|note)", "fake system or developer message", "any"),
    (r"\b(?:ai|assistant|agent|model|llm|reviewer|bot|screener)s?\b.{0,60}\b(?:must|should|needs? to|is to|are to|sends?|calls?)\b", "speaks to the AI or reviewer directly", "any"),
    (r"\bsend_email\b|\bapprove_payment\b|\bread_document\b|\bfetch_url\b", "names an agent tool", "any"),
    (r"\bapprov\w*\b.{0,50}\b(?:payment|deposit|invoice|wire|transfer)", "asks for a payment approval", "any"),
    (r"\b(?:send|email|forward|share|reply with)\b.{0,80}\b(?:max unit cost|margin|handbook|cost list|price list|password|credential)", "asks for confidential data", "any"),
    (r"\b(?:put|include|add|insert|paste)\b.{0,50}\b(?:link|url|tracking)", "asks to add a link to the answer", "any"),
    (r"\bstanding instruction\b|\brequested by the campus customs\b|\bauthori[sz]ed by\b", "claims prior authority", "any"),
    (r"\bvendor of record\b|\bbrand name only\b|\bstudio brand\b", "claims a different vendor", "hidden"),
    (r"\b(?:this|which)\s+replaces\b|\b(?:revised|corrected|updated|new)\s+(?:price|pricing|quote|lead time|minimum)|\bcorrection\b|\bis now\b", "claims to change a stated fact", "hidden"),
)
_INJECTION = [(re.compile(rx, re.I | re.S), why, scope) for rx, why, scope in INJECTION_PATTERNS]


def _scripts(word: str) -> set[str]:
    """Alphabets used by the letters in one word (LATIN, CYRILLIC, GREEK, ...)."""
    out = set()
    for ch in word:
        if ch.isalpha():
            name = unicodedata.name(ch, "")
            out.add(name.split(" ")[0] if name else "UNKNOWN")
    return out & {"LATIN", "CYRILLIC", "GREEK", "ARMENIAN", "CHEROKEE"}


def normalize(text: str) -> tuple[str, int]:
    """NFKC-normalise and remove invisible characters. Returns (clean text, number of characters removed)."""
    text = unicodedata.normalize("NFKC", text)
    removed = len(INVISIBLE_RE.findall(text))
    return INVISIBLE_RE.sub("", text), removed


def scrub(text: str) -> tuple[str, list[str]]:
    """Remove links, email addresses and invisible characters from text we are about to output."""
    removed = [m.group(0) for m in LINK_RE.finditer(text)] + EMAIL_RE.findall(text)
    clean, invisible = normalize(text)
    clean = EMAIL_RE.sub("", LINK_RE.sub("", clean))
    if invisible:
        removed.append(f"{invisible} invisible character(s)")
    return " ".join(clean.split()), removed


@dataclass
class ScreenResult:
    visible_text: str                      # what a person sees, normalised (used to fact-check the answer)
    model_text: str                        # what the model is given: visible text, links neutralised, capped
    hidden: list[dict[str, str]]           # every hidden piece and where it was hidden
    findings: list[dict[str, str]] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return any(f["severity"] in ("medium", "high") for f in self.findings)

    def summary(self) -> dict[str, Any]:
        return {"visible_chars": len(self.visible_text), "model_chars": len(self.model_text),
                "hidden_pieces": len(self.hidden), "findings": self.findings}


def screen_document(path: Path) -> ScreenResult:
    findings: list[dict[str, str]] = []
    try:
        visible, hidden = human_view(path)
    except Exception as exc:  # unreadable structure: fall back to plain extraction but force review
        from tools import extract_text

        visible, hidden = extract_text(path), []
        findings.append({"severity": "medium", "kind": "unverifiable", "where": "whole document",
                         "text": "", "reason": f"could not check what a person sees ({type(exc).__name__})"})

    visible, invisible = normalize(visible)
    if invisible:
        findings.append({"severity": "medium", "kind": "invisible_characters", "where": "visible text",
                         "text": "", "reason": f"{invisible} zero-width or control character(s) removed"})

    for h in hidden:
        text, _ = normalize(h["text"])
        pattern_hits = [why for rx, why, _ in _INJECTION if rx.search(text)]
        has_fact = bool(re.search(r"\$\s?\d|\d+(?:\.\d+)?\s*(?:business\s+)?(?:days?|units?)|\d+\.\d{2}\b", text, re.I))
        if h.get("shown"):  # text the stylesheet draws on screen: a person sees it, the page text does not hold it
            findings.append({
                "severity": "high" if (has_fact or pattern_hits) else "info", "kind": "css_drawn_text",
                "where": h["where"], "text": text[:160],
                "reason": "the page shows text drawn by its stylesheet, not written in the page text (added to what the "
                          "model reads)" + (f" ({'; '.join(pattern_hits)})" if pattern_hits else "")})
            continue
        if "page code" in h["where"] and not pattern_hits:
            findings.append({"severity": "info", "kind": "page_code", "where": h["where"], "text": text[:160],
                             "reason": "normal page code a browser does not display"})
            continue
        if h["where"].startswith("HTML attribute") and not (pattern_hits or has_fact):
            findings.append({"severity": "info", "kind": "attribute_text", "where": h["where"], "text": text[:160],
                             "reason": "ordinary attribute text (alt text, titles), not shown as page text"})
            continue
        severity = "high" if (pattern_hits or has_fact) else "medium"
        findings.append({"severity": severity, "kind": "hidden_text", "where": h["where"], "text": text[:160],
                         "reason": "hidden text removed before the model" + (f" ({'; '.join(pattern_hits)})" if pattern_hits else "")})

    mixed = sorted({w for w in re.findall(r"\w+", visible) if len(_scripts(w)) > 1})
    if mixed:
        findings.append({"severity": "high", "kind": "look_alike_letters", "where": "visible text",
                         "text": ", ".join(mixed)[:160],
                         "reason": "words mix look-alike letters from different alphabets (e.g. Cyrillic 'а' in a Latin "
                                   "name), a common way to impersonate a vendor"})

    for rx, why, scope in _INJECTION:
        if scope == "any" and (m := rx.search(visible)):
            findings.append({"severity": "high", "kind": "visible_instruction", "where": "visible text",
                             "text": m.group(0)[:160], "reason": f"visible text {why}"})

    model_text, links = LINK_RE.subn("[link removed]", visible)
    if links:
        findings.append({"severity": "low", "kind": "links_removed", "where": "visible text", "text": "",
                         "reason": f"{links} web link(s) replaced with [link removed]"})
    if len(model_text) > MAX_MODEL_CHARS:
        model_text = model_text[:MAX_MODEL_CHARS] + "\n[document truncated]"
        findings.append({"severity": "medium", "kind": "truncated", "where": "whole document", "text": "",
                         "reason": f"document longer than {MAX_MODEL_CHARS:,} characters was cut"})
    return ScreenResult(visible_text=visible, model_text=model_text, hidden=hidden, findings=findings)


# ---------------------------------------------------------------------------------------------
# Answer checks
# ---------------------------------------------------------------------------------------------


def value_visible(field_name: str, value: Any, visible: str) -> bool | None:
    """Does the answer's value appear in what a person sees? None when there is nothing to check."""
    if value is None or field_name == "decision":
        return None
    v = unicodedata.normalize("NFKC", visible).casefold().replace(",", "")
    if field_name == "unit_price":
        x = float(value)
        forms = {f"{x:.2f}"} | ({f"{int(x)}"} if x == int(x) else set())
        return any(re.search(rf"(?<![\d.]){re.escape(f)}(?![\d])", v) for f in forms)
    if field_name in ("lead_time_days", "min_order"):
        return re.search(rf"(?<![\d.]){int(value)}(?![\d.])", v) is not None
    target = " ".join(str(value).casefold().split()).rstrip(".")
    return target in " ".join(v.split())


FACT_FIELDS = ("vendor", "sku", "unit_price", "lead_time_days", "min_order")


def facts_not_visible(facts: dict[str, Any], visible: str) -> list[str]:
    return [f for f in FACT_FIELDS if value_visible(f, facts.get(f), visible) is False]
