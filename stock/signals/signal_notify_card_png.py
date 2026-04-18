"""
将通知卡片配置渲染为 PNG（PIL），供飞书上传发图；风格与 HTML 卡片大致一致。
"""

from __future__ import annotations

import io
import os
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from signals.signal_notify_card import normalize_notify_card_input

_CANVAS_W = 720
_PAD_X = 44
_PAD_Y = 40
_ROW_GAP = 10

# 主色红（偏金融信号风）
_RED = (239, 68, 68)          # #ef4444
_RED_DARK = (127, 29, 29)     # #7f1d1d
_PINK = (251, 113, 133)       # #fb7185
_BG0 = (13, 10, 12)           # near-black with warm tint
_FG = (255, 247, 247)         # warm white
_MUTED = (203, 190, 190)
_LINE = (73, 40, 40)
_CARD = (24, 12, 14)
_CARD2 = (18, 10, 12)


def _font_paths() -> List[str]:
    return [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "C:\\Windows\\Fonts\\msyh.ttc",
        "C:\\Windows\\Fonts\\simhei.ttf",
    ]


def _font_line_height(font: ImageFont.ImageFont, fallback: int) -> int:
    return int(getattr(font, "size", None) or fallback)


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for p in _font_paths():
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> Tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def _gradient_vertical(w: int, h: int, top: Tuple[int, int, int], bottom: Tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGB", (w, h), top)
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        r = _lerp(top[0], bottom[0], t)
        g = _lerp(top[1], bottom[1], t)
        b = _lerp(top[2], bottom[2], t)
        for x in range(w):
            px[x, y] = (r, g, b)
    return img


def _rounded_rect(draw: ImageDraw.ImageDraw, xy, radius: int, fill, outline=None, width: int = 1):
    # PIL 9+ 支持 rounded_rectangle
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _pill(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, font: ImageFont.ImageFont, bg, fg) -> Tuple[int, int]:
    tw, th = _text_size(draw, text, font)
    px = 14
    py = 8
    w = tw + px * 2
    h = th + py * 2
    _rounded_rect(draw, (x, y, x + w, y + h), radius=h // 2, fill=bg, outline=None)
    draw.text((x + px, y + py - 1), text, fill=fg, font=font)
    return w, h


def _pill_measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> Tuple[int, int]:
    tw, th = _text_size(draw, text, font)
    px = 14
    py = 8
    return tw + px * 2, th + py * 2

def _wrap_text(text: str, font: ImageFont.ImageFont, draw: ImageDraw.ImageDraw, max_width: int) -> List[str]:
    if not text:
        return [""]
    lines: List[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            lines.append("")
            continue
        cur = ""
        for ch in line:
            trial = cur + ch
            w, _ = _text_size(draw, trial, font)
            if w <= max_width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = ch
        if cur:
            lines.append(cur)
    return lines if lines else [""]


def render_notify_card_png(card_input: Optional[Dict[str, Any]]) -> bytes:
    """
    根据与 API / NOTIFY_CONFIG 相同的字典结构生成 PNG 字节。
    """
    n = normalize_notify_card_input(card_input)

    title_f = _load_font(30)
    sub_f = _load_font(18)
    name_f = _load_font(44)
    code_f = _load_font(22)
    row_lab_f = _load_font(20)
    row_val_f = _load_font(24)
    hi_f = _load_font(28)
    small_f = _load_font(18)

    rows: List[Dict[str, Any]] = list(n["rows"])
    # 高度预估（更宽松，避免拥挤）
    h = _PAD_Y * 2 + 160
    dummy0 = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    h += _text_size(dummy0, n["stockName"], name_f)[1]
    h += 38
    for r in rows:
        lab = str(r.get("label") or "")
        val = str(r.get("value") or "")
        style = str(r.get("style") or "default")
        vf = row_val_f
        if style == "highlight":
            vf = hi_f
        dummy = Image.new("RGB", (_CANVAS_W, 4000))
        dd = ImageDraw.Draw(dummy)
        max_vw = _CANVAS_W - _PAD_X * 2 - 170
        vlines = _wrap_text(val, vf, dd, max_vw)
        llines = _wrap_text(lab, row_lab_f, dd, 140)
        lh = _font_line_height(vf, 24) + 10
        row_h = max(len(vlines), len(llines), 1) * lh + _ROW_GAP + 8
        h += row_h
    if n.get("remark"):
        dummy = Image.new("RGB", (_CANVAS_W, 4000))
        dd = ImageDraw.Draw(dummy)
        rlines = _wrap_text(str(n["remark"]), small_f, dd, _CANVAS_W - _PAD_X * 2)
        sh = _font_line_height(small_f, 17) + 4
        h += 30 + len(rlines) * (sh + 2)
    if n.get("timestamp"):
        h += 40

    # 背景渐变（深红黑）
    img = _gradient_vertical(_CANVAS_W, max(h, 460), _BG0, _RED_DARK)
    draw = ImageDraw.Draw(img)
    y = _PAD_Y

    # 卡片主体
    card_x0 = _PAD_X
    card_y0 = _PAD_Y
    card_x1 = _CANVAS_W - _PAD_X
    card_y1 = img.height - _PAD_Y
    _rounded_rect(draw, (card_x0, card_y0, card_x1, card_y1), radius=28, fill=_CARD, outline=_LINE, width=2)

    # 卡片内边距
    x = card_x0 + 28
    y = card_y0 + 26

    # 顶部标题 + 徽标
    draw.text((x, y), n["title"], fill=_FG, font=title_f)
    tw, th = _text_size(draw, n["title"], title_f)
    _pill(draw, card_x1 - 28 - 140, y + 2, str(n.get("badgeText") or "信号"), small_f, bg=_RED, fg=_FG)
    y += th + 6
    draw.text((x, y), n["subtitle"], fill=_MUTED, font=sub_f)
    y += _text_size(draw, n["subtitle"], sub_f)[1] + 18

    # 股票名称/代码（名称一定要有，且居中显示）
    stock_name = str(n.get("stockName") or "").strip() or "—"
    stock_code = str(n.get("stockCode") or "").strip() or "—"
    card_inner_w = (card_x1 - 28) - x
    sn_w, sn_h = _text_size(draw, stock_name, name_f)
    draw.text((x + (card_inner_w - sn_w) // 2, y), stock_name, fill=_FG, font=name_f)
    y += sn_h + 10
    pill_w, _ = _pill_measure(draw, stock_code, code_f)
    _pill(draw, x + (card_inner_w - pill_w) // 2, y, stock_code, code_f, bg=_CARD2, fg=_PINK)
    y += 46

    draw.line([(x, y), (card_x1 - 28, y)], fill=_LINE, width=2)
    y += 18

    for r in rows:
        lab = str(r.get("label") or "")
        val = str(r.get("value") or "")
        style = str(r.get("style") or "default")
        vf = row_val_f
        vcolor: Tuple[int, int, int] = _FG
        if style == "mono":
            vcolor = _PINK
        elif style == "highlight":
            vf = hi_f
            vcolor = _RED
        elif style == "alert":
            vcolor = _RED
        elif style == "accent":
            vcolor = _PINK

        max_vw = (card_x1 - 28) - x - 170
        vlines = _wrap_text(val, vf, draw, max_vw)
        llines = _wrap_text(lab, row_lab_f, draw, 160)
        row_top = y
        lh = max(len(vlines), len(llines), 1)
        line_h = _font_line_height(vf, 24) + 10
        for i in range(lh):
            ly = row_top + i * line_h
            if i < len(llines):
                draw.text((x, ly), llines[i], fill=_MUTED, font=row_lab_f)
            if i < len(vlines):
                tw, _ = _text_size(draw, vlines[i], vf)
                draw.text((card_x1 - 28 - tw, ly), vlines[i], fill=vcolor, font=vf)
        y = row_top + lh * line_h + _ROW_GAP + 6

    if n.get("remark"):
        y += 10
        rlines = _wrap_text(str(n["remark"]), small_f, draw, _CANVAS_W - _PAD_X * 2)
        sh = _font_line_height(small_f, 17) + 4
        draw.line([(x, y), (card_x1 - 28, y)], fill=_LINE, width=1)
        y += 14
        for line in rlines:
            draw.text((x, y), line, fill=_MUTED, font=small_f)
            y += sh + 2

    if n.get("timestamp"):
        y += 8
        ts = str(n["timestamp"])
        tw, th = _text_size(draw, ts, small_f)
        draw.text(((card_x0 + card_x1 - tw) // 2, y), ts, fill=_MUTED, font=small_f)
        y += th

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
