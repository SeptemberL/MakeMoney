"""
将涨停复盘 report.json 渲染为 PNG（标题 + 表格，支持分页）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PngRenderOptions:
    page_size: int = 30
    width: int = 1400
    padding: int = 24
    row_height: int = 34
    header_height: int = 90
    table_header_height: int = 40
    font_size: int = 22
    font_size_small: int = 18


def _default_input_json_path(trade_date_dash: str) -> Path:
    return Path(__file__).resolve().parent.parent / "outputs" / "daily_limitup_report" / trade_date_dash / "report.json"


def _default_output_dir(trade_date_dash: str) -> Path:
    return Path(__file__).resolve().parent.parent / "outputs" / "daily_limitup_report_png" / trade_date_dash


def _coalesce(*vals: Any, default: str = "--") -> str:
    for v in vals:
        if v is None:
            continue
        s = str(v).strip()
        if s == "" or s.lower() == "none":
            continue
        return s
    return default


def _fmt_float(v: Any, *, digits: int = 2) -> str:
    if v is None:
        return "--"
    try:
        f = float(v)
        return f"{f:.{digits}f}"
    except Exception:
        return "--"


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """
    尽量加载可用的中文字体；失败则回退到 PIL 默认字体（可能不含中文）。
    """
    candidates = [
        # macOS 常见
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        # Windows 常见
        "C:\\Windows\\Fonts\\msyh.ttc",
        "C:\\Windows\\Fonts\\simhei.ttf",
        # Linux 常见
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for p in candidates:
        try:
            if Path(p).exists():
                return ImageFont.truetype(p, size=size)
        except Exception:
            continue
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size=size)
    except Exception:
        return ImageFont.load_default()


def read_daily_limitup_report_json(
    *,
    trade_date: Optional[str] = None,
    input_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    trade_date: YYYY-MM-DD
    """
    if input_path:
        path = Path(input_path)
    else:
        if not trade_date:
            raise ValueError("trade_date 或 input_path 至少提供一个")
        path = _default_input_json_path(trade_date)
    if not path.exists():
        raise FileNotFoundError(str(path))
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _split_pages(rows: Sequence[dict], page_size: int) -> List[List[dict]]:
    if page_size <= 0:
        return [list(rows)]
    out: List[List[dict]] = []
    buf: List[dict] = []
    for r in rows:
        buf.append(r)
        if len(buf) >= page_size:
            out.append(buf)
            buf = []
    if buf:
        out.append(buf)
    return out


def _measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> Tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def _draw_cell_text(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    w: int,
    h: int,
    text: str,
    font: ImageFont.ImageFont,
    fill: Tuple[int, int, int],
    align: str = "left",
    pad_x: int = 10,
):
    t = text or "--"
    tw, th = _measure(draw, t, font)
    if align == "right":
        tx = x + w - pad_x - tw
    elif align == "center":
        tx = x + (w - tw) // 2
    else:
        tx = x + pad_x
    ty = y + (h - th) // 2
    draw.text((tx, ty), t, font=font, fill=fill)


def render_daily_limitup_report_png_pages(
    report: Dict[str, Any],
    *,
    options: Optional[PngRenderOptions] = None,
) -> List[Image.Image]:
    opt = options or PngRenderOptions()

    trade_date = _coalesce(report.get("trade_date"), default="unknown-date")
    generated_at = _coalesce(report.get("generated_at"), default="")
    rows = report.get("rows") or []
    if not isinstance(rows, list):
        rows = []

    pages = _split_pages(rows, opt.page_size)
    font = _load_font(opt.font_size)
    font_small = _load_font(opt.font_size_small)

    # 列定义：标题 + 宽度 + 对齐
    cols = [
        ("代码", 110, "left"),
        ("名称", 220, "left"),
        ("连板", 80, "right"),
        ("首板时间", 130, "left"),
        ("封死时间", 130, "left"),
        ("首板换手%", 120, "right"),
        ("收盘换手%", 120, "right"),
        ("状态", 90, "left"),
        ("原因", 280, "left"),
    ]
    table_w = sum(w for _, w, _ in cols)
    width = max(opt.width, table_w + opt.padding * 2)

    images: List[Image.Image] = []
    for pi, page_rows in enumerate(pages, start=1):
        height = opt.padding * 2 + opt.header_height + opt.table_header_height + opt.row_height * len(page_rows) + 20
        img = Image.new("RGB", (width, height), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        # header
        title = f"涨停复盘（{trade_date}）"
        sub = f"生成时间：{generated_at}    共 {len(rows)} 条    第 {pi}/{len(pages)} 页"
        draw.text((opt.padding, opt.padding), title, font=font, fill=(20, 20, 20))
        draw.text((opt.padding, opt.padding + 42), sub, font=font_small, fill=(80, 80, 80))

        # table header background
        x0 = opt.padding
        y0 = opt.padding + opt.header_height
        draw.rectangle((x0, y0, x0 + table_w, y0 + opt.table_header_height), fill=(245, 247, 250), outline=(220, 220, 220))

        # col headers
        cx = x0
        for name, w, align in cols:
            _draw_cell_text(draw, x=cx, y=y0, w=w, h=opt.table_header_height, text=name, font=font_small, fill=(50, 50, 50), align="center")
            cx += w
        # vertical lines
        cx = x0
        for _, w, _ in cols:
            draw.line((cx, y0, cx, y0 + opt.table_header_height + opt.row_height * len(page_rows)), fill=(220, 220, 220), width=1)
            cx += w
        draw.line((x0 + table_w, y0, x0 + table_w, y0 + opt.table_header_height + opt.row_height * len(page_rows)), fill=(220, 220, 220), width=1)

        # rows
        for ri, r in enumerate(page_rows):
            yy = y0 + opt.table_header_height + ri * opt.row_height
            bg = (255, 255, 255) if ri % 2 == 0 else (252, 252, 252)
            status = _coalesce(r.get("status"), default="--")
            if status == "partial":
                bg = (255, 250, 240)
            draw.rectangle((x0, yy, x0 + table_w, yy + opt.row_height), fill=bg, outline=(235, 235, 235))

            values = [
                _coalesce(r.get("code")),
                _coalesce(r.get("name")),
                _coalesce(r.get("consecutive_limitup_days")),
                _coalesce(r.get("first_limitup_time")),
                _coalesce(r.get("final_seal_time")),
                _fmt_float(r.get("turnover_at_first_limitup")),
                _fmt_float(r.get("turnover_eod")),
                status,
                _coalesce(r.get("reason"), default=""),
            ]

            cx = x0
            for (col_name, w, align), v in zip(cols, values):
                fill = (50, 50, 50)
                if col_name in ("状态",) and status == "partial":
                    fill = (180, 120, 0)
                _draw_cell_text(draw, x=cx, y=yy, w=w, h=opt.row_height, text=str(v), font=font_small, fill=fill, align=("right" if align == "right" else "left"))
                cx += w

        # outer border
        draw.rectangle((x0, y0, x0 + table_w, y0 + opt.table_header_height + opt.row_height * len(page_rows)), outline=(200, 200, 200), width=1)

        images.append(img)

    return images


def write_daily_limitup_report_png(
    report: Dict[str, Any],
    *,
    output_dir: Optional[str] = None,
    options: Optional[PngRenderOptions] = None,
) -> List[str]:
    trade_date = _coalesce(report.get("trade_date"), default="unknown-date")
    out_dir = Path(output_dir) if output_dir else _default_output_dir(trade_date)
    out_dir.mkdir(parents=True, exist_ok=True)

    images = render_daily_limitup_report_png_pages(report, options=options)
    paths: List[str] = []
    for i, img in enumerate(images, start=1):
        p = out_dir / f"page_{i}.png"
        img.save(p, format="PNG", optimize=True)
        paths.append(str(p))
    return paths


def run_daily_limitup_report_png(trade_date: Optional[str] = None) -> Dict[str, Any]:
    """
    任务入口：生成指定日期的 PNG（默认使用输入 JSON 的 trade_date）。
    """
    try:
        if trade_date is None:
            # 默认选择“最新可用输入 JSON”的日期
            base = Path(__file__).resolve().parent.parent / "outputs" / "daily_limitup_report"
            if not base.exists():
                raise FileNotFoundError(str(base))
            candidates = [p for p in base.iterdir() if p.is_dir() and (p / "report.json").exists()]
            if not candidates:
                raise FileNotFoundError("未找到任何 daily_limitup_report 输出（report.json）")
            # 目录名为 YYYY-MM-DD
            trade_date = sorted([p.name for p in candidates])[-1]

        report = read_daily_limitup_report_json(trade_date=trade_date)
        paths = write_daily_limitup_report_png(report)
        logger.info("daily_limitup_report_png 完成: %s pages=%d", trade_date, len(paths))
        return {"success": True, "trade_date": trade_date, "pages": len(paths), "paths": paths}
    except Exception as e:
        logger.error("daily_limitup_report_png 失败: %s", e, exc_info=True)
        return {"success": False, "message": str(e)}

