#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PHAROS BBox Editor
==================
GUI tool to edit bounding-box polygons and reading order.
バウンディングボックス(ポリゴン)と読み取り順を編集する GUI ツール。

- Reads txt from bbox_res (read-only); edits are saved to bbox_gt.
- If a bbox_gt file already exists, it is loaded instead of bbox_res.
- Page images are loaded from each document's "pages" folder (0000.jpg ...).
- Line format: <category> x1 y1 x2 y2 ... xn yn   (variable vertex count)
- Negative coordinates (e.g. -1) are clamped to 0 on load.

The interface language can be switched between English and Japanese from the
toolbar. Category labels are always shown in English.

Requirements:  pip install PySide6
Run:
    # Folder mode (browse the whole dataset) — no arguments:
    python pharos_bbox_editor.py
    # Single-page mode — three file arguments:
    python pharos_bbox_editor.py --image PAGE.jpg --box_res RES.txt --bbox_gt GT.txt
"""

import sys
import re
import argparse
from pathlib import Path
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QLineF, QTimer
from PySide6.QtGui import (
    QAction, QBrush, QColor, QPen, QPainter, QPixmap, QFont,
    QKeySequence, QPolygonF, QPainterPath, QPainterPathStroker,
    QImageReader,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QGraphicsView, QGraphicsScene,
    QGraphicsRectItem, QGraphicsPolygonItem, QGraphicsItem, QFileDialog,
    QListWidget, QListWidgetItem, QToolBar, QMessageBox, QDialog,
    QFormLayout, QSpinBox, QDialogButtonBox, QLabel, QWidget,
    QVBoxLayout, QHBoxLayout, QPushButton, QSplitter, QLineEdit,
    QStyleFactory, QMenu, QComboBox, QSizePolicy, QInputDialog,
)

# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------

DEFAULT_ROOT = r"\\10.50.100.152\StorageServer\Data\PHAROS\pharos_epirotic\000"

IMG_EXTS = [".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"]
# Prefer the "pages" folder (higher quality), with fallbacks.
IMG_SUBDIRS = ["pages", "page", "images", "image", "img", "imgs", ""]

CATEGORY_COLORS = [
    "#4FC3F7", "#81C784", "#FFB74D", "#E57373", "#BA68C8",
    "#4DB6AC", "#FFF176", "#F06292", "#7986CB", "#A1887F",
    "#90A4AE", "#AED581", "#FF8A65", "#9575CD", "#4DD0E1",
]

# ---------------------------------------------------------------------------
# Category id -> English name. (Labels are English ONLY, in both languages.)
# This is a placeholder layout-analysis scheme; edit the names to match the
# real PHAROS labels. Unlisted ids still work and show as "category N".
# ---------------------------------------------------------------------------
CATEGORY_NAMES = {
    0: "Text",
    1: "Header",
    2: "Paragraph Title",
    3: "Image",
    4: "Table",
    5: "Formula",
    6: "Page Number",
    7: "Document Title",
    8: "Footnote",
    9: "Caption",
    10: "Document Info",
}


def category_color(cat: int) -> QColor:
    return QColor(CATEGORY_COLORS[cat % len(CATEGORY_COLORS)])


def category_name(cat: int) -> str:
    """Full English label, e.g. 'Title'. Falls back to 'category N'."""
    return CATEGORY_NAMES.get(cat, f"category {cat}")


def category_short(cat: int) -> str:
    """Short English label for the on-canvas tag, e.g. 'Title' or 'c12'."""
    return CATEGORY_NAMES.get(cat, f"c{cat}")


def line_color(color_id: int) -> QColor:
    """A distinct, pleasant colour per text line (stable per line).
    Uses golden-ratio hue spacing so neighbouring lines differ clearly."""
    h = (color_id * 0.6180339887498949) % 1.0
    sat = 0.62 if (color_id % 2 == 0) else 0.80
    val = 0.98 if (color_id % 3 != 0) else 0.86
    return QColor.fromHsvF(h, sat, val)


# ----------------------------------------------------------------------------
# Internationalisation (English / Japanese)
# ----------------------------------------------------------------------------

LANGUAGES = [("en", "English"), ("ja", "日本語")]

STRINGS = {
    "app_title": {"en": "PHAROS BBox Editor",
                  "ja": "PHAROS BBox エディター"},
    "textline_title": {"en": "Text Line BBox & Reading Order Corrector",
                       "ja": "テキスト行 BBox・読み取り順コレクター"},
    "line_n": {"en": "Line {n}", "ja": "行 {n}"},
    # toolbar
    "open_root": {"en": "📂 Open root…", "ja": "📂 ルートを開く"},
    "add_box": {"en": "➕ Add box", "ja": "➕ ボックス追加"},
    "delete": {"en": "🗑 Delete", "ja": "🗑 削除"},
    "edit_order_cat": {"en": "✏️ Edit order/category",
                       "ja": "✏️ 順番/カテゴリー変更"},
    "prev_page": {"en": "◀ Prev page", "ja": "◀ 前のページ"},
    "next_page": {"en": "Next page ▶", "ja": "次のページ ▶"},
    "fit_width": {"en": "↔ Fit width", "ja": "↔ 幅に合わせる"},
    "fit_page": {"en": "🔍 Fit page", "ja": "🔍 全体表示"},
    "undo": {"en": "↶ Undo", "ja": "↶ 元に戻す"},
    "redo": {"en": "↷ Redo", "ja": "↷ やり直し"},
    "order_mode": {"en": "🔢 Reading order", "ja": "🔢 読み取り順モード"},
    "order_start_title": {"en": "Reading order", "ja": "読み取り順"},
    "order_start_prompt": {"en": "Start numbering from:",
                           "ja": "何番から始めますか:"},
    "order_help": {
        "en": "Reading-order mode: click boxes in the order you want "
              "(click again to undo a pick).  Enter = save,  Esc = cancel.",
        "ja": "読み取り順モード: 希望する順にボックスをクリック"
              "(もう一度クリックで取り消し)。 Enter=保存,  Esc=キャンセル。"},
    "order_progress": {"en": "Assigned {k} of {n}.  Next number = {next}.",
                       "ja": "{n} 個中 {k} 個を割り当て。 次の番号 = {next}。"},
    "order_saved": {"en": "✓ Reading order saved.",
                    "ja": "✓ 読み取り順を保存しました。"},
    "order_cancelled": {"en": "Reading order cancelled.",
                        "ja": "読み取り順をキャンセルしました。"},
    "undo_done": {"en": "Undone.", "ja": "元に戻しました。"},
    "undo_empty": {"en": "Nothing to undo.", "ja": "元に戻す操作はありません。"},
    "redo_done": {"en": "Redone.", "ja": "やり直しました。"},
    "redo_empty": {"en": "Nothing to redo.", "ja": "やり直す操作はありません。"},
    "language": {"en": "Language", "ja": "言語"},
    # panels
    "documents": {"en": "Documents", "ja": "ドキュメント"},
    "search_docs": {"en": "Search documents…", "ja": "ドキュメント検索…"},
    "pages_header": {"en": "Pages   (✓ = edited, bbox_gt exists)",
                     "ja": "ページ   (✓ = 編集済み, bbox_gt あり)"},
    "boxes_header": {"en": "Bounding boxes (reading order)",
                     "ja": "バウンディングボックス (読み取り順)"},
    "lines_header": {"en": "Text lines (reading order)",
                     "ja": "テキスト行 (読み取り順)"},
    "move_up": {"en": "▲ Move up", "ja": "▲ 順番を上げる"},
    "move_down": {"en": "▼ Move down", "ja": "▼ 順番を下げる"},
    "edit_btn": {"en": "✏️ Edit…", "ja": "✏️ 変更…"},
    # status / state
    "help": {
        "en": "Drag page or WASD / arrow keys = pan, wheel = zoom, "
              "drag box = move, drag vertex = reshape, click midpoint (+) "
              "= add point, right-click = menu | Ins=add  Del=delete  "
              "E=edit  O=order  Ctrl+0=fit width  F=fit page",
        "ja": "ページをドラッグ または WASD / 矢印キー=パン, ホイール=ズーム, "
              "ボックス内ドラッグ=移動, 頂点ドラッグ=変形, 中点(＋)クリック=ポイント追加, "
              "右クリック=メニュー | Ins=追加 Del=削除 E=編集 O=読み取り順 "
              "Ctrl+0=幅に合わせる F=全体表示",
    },
    "showing_gt": {"en": "📄 Showing corrected (bbox_gt)",
                   "ja": "📄 編集済み (bbox_gt) を表示中"},
    "showing_res": {"en": "📄 Showing model output (bbox_res)",
                    "ja": "📄 元データ (bbox_res) を表示中"},
    "loaded_docs": {"en": "Loaded {n} document(s).",
                    "ja": "{n} 個のドキュメントを読み込みました。"},
    "add_mode_msg": {
        "en": "Add mode: drag on the page to draw a new box. You can add "
              "more points afterwards to make any shape.",
        "ja": "追加モード: キャンバス上でドラッグして新しいボックスを描いてください。"
              "(追加後にポイントを増やして自由な形にできます)",
    },
    "saved_msg": {"en": "✓ Saved → {path}", "ja": "✓ 保存しました → {path}"},
    # dialogs
    "dlg_add_title": {"en": "Add box", "ja": "ボックスを追加"},
    "dlg_edit_title": {"en": "Edit order / category",
                       "ja": "順番 / カテゴリーの変更"},
    "f_category": {"en": "Category:", "ja": "カテゴリー:"},
    "f_order": {"en": "Reading order:", "ja": "読み取り順:"},
    "order_hint": {"en": "Changing the order shifts the other boxes "
                         "accordingly.",
                   "ja": "順番を変更すると、他のボックスの順番も自動的にずれます。"},
    "choose_root_title": {
        "en": "Select root folder (e.g. …\\pharos_epirotic\\000)",
        "ja": "ルートフォルダーを選択 (例: …\\pharos_epirotic\\000)"},
    "err_title": {"en": "Error", "ja": "エラー"},
    "cannot_open_folder": {"en": "Cannot open folder:\n{e}",
                           "ja": "フォルダーを開けません:\n{e}"},
    "save_err_title": {"en": "Save error", "ja": "保存エラー"},
    "save_err_body": {"en": "Could not write the file:\n{e}",
                      "ja": "書き込みに失敗しました:\n{e}"},
    "del_title": {"en": "Confirm delete", "ja": "削除の確認"},
    "del_body": {
        "en": "Delete box at reading order {i} ({name})?\n"
              "The following boxes shift up.",
        "ja": "読み取り順 {i} ({name}) のボックスを削除しますか?\n"
              "後続のボックスの順番は自動的に繰り上がります。"},
    # context menu (on a box)
    "ctx_del_point": {"en": "Delete this point", "ja": "このポイントを削除"},
    "ctx_add_point": {"en": "Add point here", "ja": "ここにポイントを追加"},
    "ctx_edit": {"en": "Edit order / category…",
                 "ja": "順番 / カテゴリーを変更…"},
    "ctx_del_box": {"en": "Delete box", "ja": "ボックスを削除"},
}

_lang = "en"


def set_lang(code: str):
    global _lang
    if code in (c for c, _ in LANGUAGES):
        _lang = code


def tr(key: str, **kw) -> str:
    entry = STRINGS.get(key, {})
    s = entry.get(_lang) or entry.get("en") or key
    return s.format(**kw) if kw else s


# ----------------------------------------------------------------------------
# Data model
# ----------------------------------------------------------------------------

@dataclass
class BBox:
    category: int
    points: list = field(default_factory=list)  # [(x, y), ...] >= 3 points

    def normalize(self):
        self.points = [(max(0, int(round(x))), max(0, int(round(y))))
                       for x, y in self.points]

    def bounding(self):
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return min(xs), min(ys), max(xs), max(ys)


def load_boxes(txt_path: Path) -> list[BBox]:
    """Load a txt file, clamp negatives to 0, return list of BBox."""
    boxes: list[BBox] = []
    try:
        text = txt_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return boxes
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            cat = int(round(float(parts[0])))
            nums = [max(0, int(round(float(p)))) for p in parts[1:]]
        except ValueError:
            continue
        if len(nums) % 2 == 1:
            nums = nums[:-1]
        pts = list(zip(nums[0::2], nums[1::2]))
        if len(pts) == 2:  # two points -> rectangle diagonal
            (x1, y1), (x2, y2) = pts
            x1, x2 = min(x1, x2), max(x1, x2)
            y1, y2 = min(y1, y2), max(y1, y2)
            pts = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
        if len(pts) < 3:
            continue
        boxes.append(BBox(cat, pts))
    return boxes


def save_boxes(txt_path: Path, boxes: list[BBox]):
    """Write boxes as: category x1 y1 ... xn yn (one box per line)."""
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for b in boxes:
        b.normalize()
        coords = " ".join(f"{x} {y}" for x, y in b.points)
        lines.append(f"{b.category} {coords}")
    txt_path.write_text("\n".join(lines) + ("\n" if lines else ""),
                        encoding="utf-8")


def load_lines(txt_path: Path) -> list[BBox]:
    """Load a 'text line' txt: each row is 'x1 y1 x2 y2 ... xn yn' (NO
    category; 4 points in the original data). Row order = reading order.
    Each line gets a stable colour id so it keeps its colour when reordered."""
    boxes: list[BBox] = []
    try:
        text = txt_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return boxes
    cid = 0
    for row in text.splitlines():
        parts = row.split()
        if len(parts) < 6:
            continue
        try:
            nums = [max(0, int(round(float(p)))) for p in parts]
        except ValueError:
            continue
        if len(nums) % 2 == 1:
            nums = nums[:-1]
        pts = list(zip(nums[0::2], nums[1::2]))
        if len(pts) < 3:
            continue
        boxes.append(BBox(cid, pts))   # category field reused as colour id
        cid += 1
    return boxes


def save_lines(txt_path: Path, boxes: list[BBox]):
    """Write text lines as 'x1 y1 ... xn yn' (NO category), one row per line,
    in reading order."""
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for b in boxes:
        b.normalize()
        rows.append(" ".join(f"{x} {y}" for x, y in b.points))
    txt_path.write_text("\n".join(rows) + ("\n" if rows else ""),
                        encoding="utf-8")


def find_page_image(doc_dir: Path, stem: str) -> Path | None:
    """Find the page image; prefer the 'pages' folder."""
    for sub in IMG_SUBDIRS:
        d = doc_dir / sub if sub else doc_dir
        if not d.is_dir():
            continue
        for ext in IMG_EXTS:
            p = d / (stem + ext)
            if p.exists():
                return p
    try:
        for p in doc_dir.rglob(stem + ".*"):
            if p.suffix.lower() in IMG_EXTS:
                return p
    except OSError:
        pass
    return None


# ----------------------------------------------------------------------------
# Graphics item (polygon)
# ----------------------------------------------------------------------------

HANDLE = 14.0  # vertex handle hit radius (screen pixels)


class BoxItem(QGraphicsPolygonItem):
    """Editable bounding box, treated as a polygon.

    - drag inside                   -> move the whole box
    - drag a vertex (square handle) -> move that vertex
    - click an edge midpoint (+)    -> insert a new vertex and drag it
    - right-click                   -> add / delete point, edit order, delete
    """

    def __init__(self, editor, index: int, box: BBox, label_px: float):
        super().__init__(QPolygonF([QPointF(x, y) for x, y in box.points]))
        self.editor = editor
        self.index = index          # 0-based (reading order - 1)
        self.box = box
        self.label_px = label_px
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.setZValue(10)
        self._drag = None
        self._press_pos = None
        self._press_poly = None
        self._dirty = False

    # ---- geometry helpers ----------------------------------------------

    def _scene_px(self, px: float) -> float:
        views = self.scene().views() if self.scene() else []
        if views:
            scale = views[0].transform().m11()
            if scale > 0:
                return px / scale
        return px

    def _midpoints(self):
        poly = self.polygon()
        n = poly.count()
        return [QPointF((poly[i].x() + poly[(i + 1) % n].x()) / 2,
                        (poly[i].y() + poly[(i + 1) % n].y()) / 2)
                for i in range(n)]

    def _vertex_at(self, pos: QPointF):
        tol = self._scene_px(HANDLE)
        poly = self.polygon()
        for i in range(poly.count()):
            if QLineF(pos, poly[i]).length() <= tol:
                return i
        return None

    def _midpoint_at(self, pos: QPointF):
        tol = self._scene_px(HANDLE)
        for i, mp in enumerate(self._midpoints()):
            if QLineF(pos, mp).length() <= tol:
                return i
        return None

    def _nearest_edge(self, pos: QPointF):
        poly = self.polygon()
        n = poly.count()
        best = (None, None, float("inf"))
        for i in range(n):
            a, b = poly[i], poly[(i + 1) % n]
            ab = b - a
            ab2 = ab.x() ** 2 + ab.y() ** 2
            if ab2 == 0:
                continue
            t = max(0.0, min(1.0, ((pos.x() - a.x()) * ab.x() +
                                   (pos.y() - a.y()) * ab.y()) / ab2))
            proj = QPointF(a.x() + ab.x() * t, a.y() + ab.y() * t)
            d = QLineF(pos, proj).length()
            if d < best[2]:
                best = (i, proj, d)
        return best

    # ---- shape / paint -------------------------------------------------

    def shape(self):
        path = QPainterPath()
        path.addPolygon(self.polygon())
        path.closeSubpath()
        stroker = QPainterPathStroker()
        stroker.setWidth(self._scene_px(10))
        path = path.united(stroker.createStroke(path))
        if self.isSelected():
            tol = self._scene_px(HANDLE)
            for pt in list(self.polygon()) + self._midpoints():
                path.addEllipse(pt, tol, tol)
        return path

    def boundingRect(self):
        m = self._scene_px(HANDLE) + self.label_px * 1.25 + 10
        return self.polygon().boundingRect().adjusted(-m, -m, m, m)

    def _paint_order_mode(self, painter: QPainter):
        """Rendering while the editor is in reading-order mode."""
        poly = self.polygon()
        num = self.editor.order_number_of(self.box)
        picked = num is not None
        accent = QColor("#2ecc71")  # green = picked
        base = self.editor.box_color(self.box)

        if picked:
            pen = QPen(accent, self._scene_px(3.4))
            fill = QColor(accent)
            fill.setAlpha(70)
        else:
            pen_col = QColor(base)
            pen_col.setAlpha(120)
            pen = QPen(pen_col, self._scene_px(1.8))
            fill = QColor(base)
            fill.setAlpha(18)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(QBrush(fill))
        painter.drawPolygon(poly)

        r = poly.boundingRect()
        if picked:
            # big centred number badge
            d = min(r.width(), r.height())
            badge = max(self.label_px * 1.4,
                        self._scene_px(34))
            badge = min(badge, d * 0.9) if d > 0 else badge
            center = r.center()
            rect = QRectF(center.x() - badge / 2, center.y() - badge / 2,
                          badge, badge)
            painter.setPen(Qt.NoPen)
            painter.setBrush(accent)
            painter.drawEllipse(rect)
            font = QFont("Segoe UI", 1)
            font.setPixelSize(max(12, int(badge * 0.6)))
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#0d1f14"))
            painter.drawText(rect, Qt.AlignCenter, str(num))
        else:
            # faint current order number, top-left
            font = QFont("Segoe UI", 1)
            font.setPixelSize(max(10, int(self.label_px * 0.9)))
            font.setBold(True)
            painter.setFont(font)
            text = f" {self.index + 1} "
            fm = painter.fontMetrics()
            bg = QRectF(r.left(), r.top() - fm.height(),
                        fm.horizontalAdvance(text), fm.height())
            if bg.top() < 0:
                bg.moveTop(r.top())
            painter.setPen(Qt.NoPen)
            c2 = QColor(base)
            c2.setAlpha(80)
            painter.setBrush(c2)
            painter.drawRect(bg)
            tc = QColor("#10141a")
            tc.setAlpha(150)
            painter.setPen(tc)
            painter.drawText(bg, Qt.AlignCenter, text)

    def paint(self, painter: QPainter, option, widget=None):
        if self.editor.order_mode:
            self._paint_order_mode(painter)
            return
        color = self.editor.box_color(self.box)
        poly = self.polygon()
        selected = self.isSelected()
        # "dim" = another box is selected, so this one steps back and hides
        # its label (overlapping labels are what hide the content).
        dim = (not selected) and self.editor.has_selection()

        # Outline + fill
        if dim:
            pen_col = QColor(color)
            pen_col.setAlpha(70)
            pen = QPen(pen_col, self._scene_px(1.4))
            fill = QColor(color)
            fill.setAlpha(10)
        else:
            pen = QPen(color, self._scene_px(2.2 if not selected else 3.6))
            fill = QColor(color)
            fill.setAlpha(46 if not selected else 70)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(QBrush(fill))
        painter.drawPolygon(poly)

        # Text-line mode: no full label, just a faint reading-order number.
        if self.editor.textline_mode:
            r = poly.boundingRect()
            lpx = self.label_px * (1.0 if selected else 0.85)
            font = QFont("Segoe UI", 1)
            font.setPixelSize(max(10, int(lpx)))
            font.setBold(True)
            painter.setFont(font)
            text = str(self.index + 1)
            fm = painter.fontMetrics()
            pad = self._scene_px(4)
            tw = fm.horizontalAdvance(text)
            th = fm.height()
            pos = QRectF(r.left() + pad, r.top() + pad, tw, th)
            alpha = 60 if dim else (210 if selected else 120)
            tc = QColor("#10141a")
            tc.setAlpha(alpha)
            painter.setPen(tc)
            painter.drawText(pos, Qt.AlignLeft | Qt.AlignVCenter, text)

        # Label (order + English category name). Hidden while dimmed so it
        # never covers the content of the box being inspected. Text-line mode
        # has no labels at all.
        if not dim and not self.editor.textline_mode:
            r = poly.boundingRect()
            lpx = self.label_px * (1.18 if selected else 1.0)
            font = QFont("Segoe UI", 1)
            font.setPixelSize(max(10, int(lpx)))
            font.setBold(True)
            painter.setFont(font)
            text = f" {self.index + 1}  {category_short(self.box.category)} "
            fm = painter.fontMetrics()
            bg = QRectF(r.left(), r.top() - fm.height(),
                        fm.horizontalAdvance(text), fm.height())
            if bg.top() < 0:
                bg.moveTop(r.top())
            painter.setPen(Qt.NoPen)
            c2 = QColor(color)
            c2.setAlpha(235 if selected else 110)
            painter.setBrush(c2)
            painter.drawRect(bg)
            txt_col = QColor("#10141a")
            txt_col.setAlpha(255 if selected else 170)
            painter.setPen(txt_col)
            painter.drawText(bg, Qt.AlignCenter, text)

        if selected:
            hs = self._scene_px(HANDLE * 0.6)
            painter.setBrush(QColor("#ffffff"))
            painter.setPen(QPen(color, self._scene_px(1.5)))
            for pt in poly:
                painter.drawRect(QRectF(pt.x() - hs / 2, pt.y() - hs / 2,
                                        hs, hs))
            rad = self._scene_px(HANDLE * 0.42)
            cross = rad * 0.55
            for mp in self._midpoints():
                painter.setBrush(QColor(255, 255, 255, 215))
                painter.setPen(QPen(color, self._scene_px(1.2)))
                painter.drawEllipse(mp, rad, rad)
                painter.setPen(QPen(QColor("#10141a"),
                                    self._scene_px(1.6)))
                painter.drawLine(QPointF(mp.x() - cross, mp.y()),
                                 QPointF(mp.x() + cross, mp.y()))
                painter.drawLine(QPointF(mp.x(), mp.y() - cross),
                                 QPointF(mp.x(), mp.y() + cross))

    # ---- mouse ---------------------------------------------------------

    def hoverMoveEvent(self, event):
        if self.isSelected():
            if self._vertex_at(event.pos()) is not None:
                self.setCursor(Qt.SizeAllCursor)
            elif self._midpoint_at(event.pos()) is not None:
                self.setCursor(Qt.CrossCursor)
            else:
                self.setCursor(Qt.SizeAllCursor)
        else:
            self.setCursor(Qt.PointingHandCursor)
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.editor.order_mode:
            self.editor.order_click(self.index)
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            was_selected = self.isSelected()
            self.editor.select_box(self.index, from_scene=True)
            pos = event.pos()
            self._press_pos = pos
            self._press_poly = QPolygonF(self.polygon())
            self._dirty = False
            if was_selected:
                vi = self._vertex_at(pos)
                if vi is not None:
                    self._drag = ("vertex", vi)
                    event.accept()
                    return
                mi = self._midpoint_at(pos)
                if mi is not None:
                    poly = QPolygonF(self.polygon())
                    poly.insert(mi + 1, self._midpoints()[mi])
                    self.prepareGeometryChange()
                    self.setPolygon(poly)
                    self._press_poly = QPolygonF(poly)
                    self._drag = ("vertex", mi + 1)
                    self._dirty = True
                    event.accept()
                    return
            self._drag = ("move",)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag is None:
            super().mouseMoveEvent(event)
            return
        d = event.pos() - self._press_pos
        poly = QPolygonF(self._press_poly)
        if self._drag[0] == "move":
            poly.translate(d)
        else:
            i = self._drag[1]
            poly[i] = self._press_poly[i] + d
        self.prepareGeometryChange()
        self.setPolygon(poly)
        self._dirty = True
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._drag is not None:
            if self._dirty:
                self._commit()
            self._drag = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.editor.order_mode:
            event.accept()
            return
        self.editor.edit_box_dialog(self.index)
        event.accept()

    def contextMenuEvent(self, event):
        if self.editor.order_mode:
            event.ignore()
            return
        self.editor.select_box(self.index, from_scene=True)
        pos = event.pos()
        menu = QMenu()
        vi = self._vertex_at(pos)
        edge_i, proj, dist = self._nearest_edge(pos)

        act_add = act_del = None
        if vi is not None:
            act_del = menu.addAction(tr("ctx_del_point"))
            act_del.setEnabled(self.polygon().count() > 3)
        elif edge_i is not None and dist <= self._scene_px(HANDLE * 2):
            act_add = menu.addAction(tr("ctx_add_point"))
        menu.addSeparator()
        act_edit = menu.addAction(tr("ctx_edit"))
        act_remove = menu.addAction(tr("ctx_del_box"))

        chosen = menu.exec(event.screenPos())
        if chosen is None:
            return
        if chosen is act_del:
            poly = QPolygonF(self.polygon())
            poly.remove(vi)
            self.prepareGeometryChange()
            self.setPolygon(poly)
            self._commit()
        elif chosen is act_add:
            poly = QPolygonF(self.polygon())
            poly.insert(edge_i + 1, proj)
            self.prepareGeometryChange()
            self.setPolygon(poly)
            self._commit()
        elif chosen is act_edit:
            self.editor.edit_box_dialog(self.index)
        elif chosen is act_remove:
            self.editor.delete_box(self.index)
        event.accept()

    def _commit(self):
        self.editor.push_undo()
        self.box.points = [(p.x(), p.y()) for p in self.polygon()]
        self.box.normalize()
        self.prepareGeometryChange()
        self.setPolygon(QPolygonF([QPointF(x, y)
                                   for x, y in self.box.points]))
        self._dirty = False
        self.editor.box_geometry_changed(self.index)


# ----------------------------------------------------------------------------
# Canvas (zoom / pan / draw new box)
# ----------------------------------------------------------------------------

class CanvasView(QGraphicsView):
    boxDrawn = Signal(QRectF)

    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHints(QPainter.Antialiasing |
                            QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QColor("#14181f"))
        self.setDragMode(QGraphicsView.NoDrag)
        self.add_mode = False
        self._rubber_item = None
        self._rubber_origin = None
        self._panning = False
        self._pan_start = QPointF()
        self.setCursor(Qt.OpenHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    # WASD and arrow keys pan the image (WASD does nothing but pan).
    PAN_KEYS = {
        Qt.Key_W: (0, -1), Qt.Key_S: (0, 1),
        Qt.Key_A: (-1, 0), Qt.Key_D: (1, 0),
        Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1),
        Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0),
    }

    def pan_by(self, dx: int, dy: int):
        h = self.horizontalScrollBar()
        v = self.verticalScrollBar()
        h.setValue(h.value() + dx)
        v.setValue(v.value() + dy)

    def keyPressEvent(self, event):
        d = self.PAN_KEYS.get(event.key())
        if d is not None:
            step = 220 if (event.modifiers() & Qt.ShiftModifier) else 90
            self.pan_by(d[0] * step, d[1] * step)
            event.accept()
            return
        super().keyPressEvent(event)

    def set_add_mode(self, on: bool):
        self.add_mode = on
        self.setCursor(Qt.CrossCursor if on else Qt.OpenHandCursor)

    def wheelEvent(self, event):
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)
        self.scene().update()

    def _box_item_at(self, view_pos) -> bool:
        scene_pos = self.mapToScene(view_pos.toPoint())
        for it in self.scene().items(scene_pos):
            if isinstance(it, BoxItem):
                return True
        return False

    def mousePressEvent(self, event):
        on_background = (not self.add_mode and
                         not self._box_item_at(event.position()))
        if event.button() == Qt.MiddleButton or (
                event.button() == Qt.LeftButton and not self.add_mode and
                (event.modifiers() & Qt.ShiftModifier or on_background)):
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        if self.add_mode and event.button() == Qt.LeftButton:
            self._rubber_origin = self.mapToScene(event.position().toPoint())
            self._rubber_item = QGraphicsRectItem(
                QRectF(self._rubber_origin, self._rubber_origin))
            pen = QPen(QColor("#4FC3F7"), 2, Qt.DashLine)
            pen.setCosmetic(True)
            self._rubber_item.setPen(pen)
            self._rubber_item.setBrush(QColor(79, 195, 247, 40))
            self._rubber_item.setZValue(100)
            self.scene().addItem(self._rubber_item)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            d = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(d.y()))
            event.accept()
            return
        if self._rubber_item is not None:
            p = self.mapToScene(event.position().toPoint())
            self._rubber_item.setRect(
                QRectF(self._rubber_origin, p).normalized())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning and event.button() in (Qt.MiddleButton,
                                                Qt.LeftButton):
            self._panning = False
            self.setCursor(Qt.CrossCursor if self.add_mode
                           else Qt.OpenHandCursor)
            event.accept()
            return
        if self._rubber_item is not None and event.button() == Qt.LeftButton:
            rect = self._rubber_item.rect().normalized()
            self.scene().removeItem(self._rubber_item)
            self._rubber_item = None
            if rect.width() > 4 and rect.height() > 4:
                self.boxDrawn.emit(rect)
            event.accept()
            return
        super().mouseReleaseEvent(event)


# ----------------------------------------------------------------------------
# Dialog
# ----------------------------------------------------------------------------

class BoxDialog(QDialog):
    """Category + reading order (used for both Add and Edit)."""

    def __init__(self, parent, title: str, n_boxes: int,
                 category: int = 0, order: int | None = None,
                 allow_order_n_plus_1: bool = False,
                 show_category: bool = True):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(330)
        form = QFormLayout(self)
        self.show_category = show_category

        # Category dropdown: "id — English name" (names are English only).
        self.cat_combo = None
        if show_category:
            self.cat_combo = QComboBox()
            self.cat_combo.setEditable(True)
            self.cat_combo.setInsertPolicy(QComboBox.NoInsert)
            for n in sorted(CATEGORY_NAMES):
                self.cat_combo.addItem(f"{n} — {CATEGORY_NAMES[n]}", n)
            idx = self.cat_combo.findData(category)
            if idx >= 0:
                self.cat_combo.setCurrentIndex(idx)
            else:
                self.cat_combo.setCurrentText(str(category))
            form.addRow(tr("f_category"), self.cat_combo)

        max_order = max(1, n_boxes + (1 if allow_order_n_plus_1 else 0))
        self.order_spin = QSpinBox()
        self.order_spin.setRange(1, max_order)
        self.order_spin.setValue(order if order else max_order)
        form.addRow(tr("f_order"), self.order_spin)

        hint = QLabel(tr("order_hint"))
        hint.setStyleSheet("color: #8a93a6; font-size: 11px;")
        hint.setWordWrap(True)
        form.addRow(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok |
                                   QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _parse_category(self) -> int:
        if not self.show_category or self.cat_combo is None:
            return 0
        idx = self.cat_combo.currentIndex()
        text = self.cat_combo.currentText().strip()
        if idx >= 0 and self.cat_combo.itemText(idx) == text:
            return int(self.cat_combo.itemData(idx))
        m = re.match(r"\s*(\d+)", text)
        return int(m.group(1)) if m else 0

    def values(self):
        return self._parse_category(), self.order_spin.value()


# ----------------------------------------------------------------------------
# Main window
# ----------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, single=None, textline=None):
        super().__init__()
        self.resize(1480, 920)

        # Single-page (terminal) mode: (image_path, res_path, gt_path)
        self.single_mode = single is not None
        self.single_image = self.single_res = self.single_gt = None
        if single:
            self.single_image, self.single_res, self.single_gt = single

        # Text-line corrector mode: (image_path, lines_src, lines_gt)
        self.textline_mode = textline is not None
        self.textline_image = self.textline_src = self.textline_gt = None
        if textline:
            self.textline_image, self.textline_src, self.textline_gt = textline

        self.root: Path | None = None
        self.doc_dir: Path | None = None
        self.txt_name: str | None = None
        self.boxes: list[BBox] = []
        self.items: list[BoxItem] = []
        self.page_rect = QRectF(0, 0, 2000, 2800)
        self.label_px = 28.0
        self._syncing = False
        self._src_state = "res"  # "res" or "gt" — for the status label
        self._undo: list[list[BBox]] = []
        self._redo: list[list[BBox]] = []
        self._undo_limit = 200
        # reading-order mode
        self.order_mode = False
        self.order_start = 1
        self.order_seq: list[BBox] = []
        self._suppress_order_toggle = False

        self._build_ui()
        self._apply_style()
        self.retranslate()

        if self.single_mode:
            # Hide folder-browsing UI; work with the single page only.
            self.left_panel.hide()
            self.act_open.setVisible(False)
            self.act_prev.setVisible(False)
            self.act_next.setVisible(False)
            self._open_single()
        elif self.textline_mode:
            self.left_panel.hide()
            self.act_open.setVisible(False)
            self.act_prev.setVisible(False)
            self.act_next.setVisible(False)
            self._open_textline()
        else:
            default = Path(DEFAULT_ROOT)
            if default.is_dir():
                self.set_root(default)

    # ---- UI -------------------------------------------------------------

    def _build_ui(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        self.act_open = QAction(self)
        self.act_open.triggered.connect(self.choose_root)
        tb.addAction(self.act_open)
        tb.addSeparator()

        self.act_add = QAction(self)
        self.act_add.setCheckable(True)
        self.act_add.setShortcut(QKeySequence(Qt.Key_Q))
        self.act_add.toggled.connect(self.toggle_add_mode)
        tb.addAction(self.act_add)

        self.act_del = QAction(self)
        self.act_del.setShortcut(QKeySequence.Delete)
        self.act_del.triggered.connect(self.delete_selected)
        tb.addAction(self.act_del)

        self.act_edit = QAction(self)
        self.act_edit.setShortcut(QKeySequence("E"))
        self.act_edit.triggered.connect(
            lambda: self.edit_box_dialog(self.selected_index()))
        tb.addAction(self.act_edit)
        tb.addSeparator()

        self.act_prev = QAction(self)
        self.act_prev.setShortcut(QKeySequence("PgUp"))
        self.act_prev.triggered.connect(lambda: self.step_page(-1))
        tb.addAction(self.act_prev)

        self.act_next = QAction(self)
        self.act_next.setShortcut(QKeySequence("PgDown"))
        self.act_next.triggered.connect(lambda: self.step_page(1))
        tb.addAction(self.act_next)
        tb.addSeparator()

        self.act_width = QAction(self)
        self.act_width.setShortcut(QKeySequence("Ctrl+0"))
        self.act_width.triggered.connect(self.fit_width)
        tb.addAction(self.act_width)

        self.act_fit = QAction(self)
        self.act_fit.setShortcut(QKeySequence("F"))
        self.act_fit.triggered.connect(self.fit_view)
        tb.addAction(self.act_fit)
        tb.addSeparator()

        self.act_undo = QAction(self)
        self.act_undo.setShortcut(QKeySequence.Undo)  # Ctrl+Z
        self.act_undo.triggered.connect(self.undo)
        tb.addAction(self.act_undo)

        self.act_redo = QAction(self)
        # Ctrl+Y (Windows) / Ctrl+Shift+Z (other platforms)
        self.act_redo.setShortcuts(
            [QKeySequence.Redo, QKeySequence("Ctrl+Shift+Z")])
        self.act_redo.triggered.connect(self.redo)
        tb.addAction(self.act_redo)
        tb.addSeparator()

        self.act_order = QAction(self)
        self.act_order.setCheckable(True)
        self.act_order.setShortcut(QKeySequence("O"))
        self.act_order.toggled.connect(self.on_order_toggled)
        tb.addAction(self.act_order)

        # Spacer pushes the language selector to the right edge.
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        self.lang_label = QLabel()
        tb.addWidget(self.lang_label)
        self.lang_combo = QComboBox()
        for code, name in LANGUAGES:
            self.lang_combo.addItem(name, code)
        self.lang_combo.setCurrentIndex(
            [c for c, _ in LANGUAGES].index(_lang))
        self.lang_combo.currentIndexChanged.connect(self.on_language_changed)
        tb.addWidget(self.lang_combo)

        # Left panel
        self.search_edit = QLineEdit()
        self.search_edit.textChanged.connect(self.filter_docs)
        self.doc_list = QListWidget()
        self.doc_list.currentItemChanged.connect(self.on_doc_changed)
        self.page_list = QListWidget()
        self.page_list.currentItemChanged.connect(self.on_page_changed)

        left = QWidget()
        self.left_panel = left
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 4, 8)
        self.lbl_documents = QLabel()
        lv.addWidget(self.lbl_documents)
        lv.addWidget(self.search_edit)
        lv.addWidget(self.doc_list, 3)
        self.lbl_pages = QLabel()
        lv.addWidget(self.lbl_pages)
        lv.addWidget(self.page_list, 2)

        # Center
        self.scene = QGraphicsScene()
        self.view = CanvasView(self.scene)
        self.view.boxDrawn.connect(self.add_box_from_rect)

        # Right panel
        self.box_list = QListWidget()
        self.box_list.currentRowChanged.connect(self.on_box_row_changed)
        self.box_list.itemDoubleClicked.connect(
            lambda _: self.edit_box_dialog(self.box_list.currentRow()))

        self.btn_up = QPushButton()
        self.btn_up.clicked.connect(lambda: self.move_selected(-1))
        self.btn_down = QPushButton()
        self.btn_down.clicked.connect(lambda: self.move_selected(1))
        self.btn_edit = QPushButton()
        self.btn_edit.clicked.connect(
            lambda: self.edit_box_dialog(self.selected_index()))
        self.btn_del = QPushButton()
        self.btn_del.clicked.connect(self.delete_selected)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 8, 8, 8)
        self.lbl_boxes = QLabel()
        self.gt_label = QLabel("")
        self.gt_label.setStyleSheet("color:#8a93a6;")
        rv.addWidget(self.lbl_boxes)
        rv.addWidget(self.gt_label)
        rv.addWidget(self.box_list, 1)
        hb = QHBoxLayout()
        hb.addWidget(self.btn_up)
        hb.addWidget(self.btn_down)
        rv.addLayout(hb)
        hb2 = QHBoxLayout()
        hb2.addWidget(self.btn_edit)
        hb2.addWidget(self.btn_del)
        rv.addLayout(hb2)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(self.view)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([260, 960, 260])
        self.setCentralWidget(splitter)

    def _apply_style(self):
        QApplication.setStyle(QStyleFactory.create("Fusion"))
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #1b212b; color: #dfe5ee;
                font-size: 13px; }
            QToolBar { background: #232a36; border: none; padding: 6px;
                spacing: 6px; }
            QToolBar QToolButton { background: transparent; padding: 6px 10px;
                border-radius: 6px; }
            QToolBar QToolButton:hover { background: #313b4d; }
            QToolBar QToolButton:checked { background: #2c5f8a; }
            QListWidget { background: #161b23; border: 1px solid #2b3342;
                border-radius: 8px; padding: 4px; }
            QListWidget::item { padding: 6px 8px; border-radius: 5px; }
            QListWidget::item:selected { background: #2c5f8a; color: #fff; }
            QListWidget::item:hover { background: #232c3a; }
            QPushButton { background: #2a3342;
                border: 1px solid #3a455a; border-radius: 6px;
                padding: 7px 10px; }
            QPushButton:hover { background: #34405a; }
            QLineEdit, QSpinBox, QComboBox { background: #161b23;
                border: 1px solid #2b3342; border-radius: 6px;
                padding: 6px 8px; }
            QComboBox QAbstractItemView { background: #161b23;
                selection-background-color: #2c5f8a; }
            QLabel { color: #aeb7c6; }
            QStatusBar { background: #232a36; color: #8a93a6; }
            QSplitter::handle { background: #232a36; width: 3px; }
            QDialog { background: #1b212b; }
            QMenu { background: #232a36; border: 1px solid #3a455a; }
            QMenu::item { padding: 6px 18px; }
            QMenu::item:selected { background: #2c5f8a; }
            QScrollBar:vertical { background: #161b23; width: 11px; }
            QScrollBar::handle:vertical { background: #3a455a;
                border-radius: 5px; min-height: 24px; }
            QScrollBar:horizontal { background: #161b23; height: 11px; }
            QScrollBar::handle:horizontal { background: #3a455a;
                border-radius: 5px; min-width: 24px; }
        """)

    # ---- i18n -----------------------------------------------------------

    def on_language_changed(self, _idx: int):
        set_lang(self.lang_combo.currentData())
        self.retranslate()

    def retranslate(self):
        if self.textline_mode and self.textline_src is not None:
            self.setWindowTitle(
                f"{tr('textline_title')} — {self.textline_src.name}")
        elif self.single_mode and self.single_gt is not None:
            self.setWindowTitle(f"{tr('app_title')} — {self.single_gt.name}")
        else:
            self.setWindowTitle(
                tr("app_title") + (f" — {self.root}" if self.root else ""))
        self.act_open.setText(tr("open_root"))
        self.act_add.setText(tr("add_box"))
        self.act_del.setText(tr("delete"))
        self.act_edit.setText(tr("edit_order_cat"))
        self.act_prev.setText(tr("prev_page"))
        self.act_next.setText(tr("next_page"))
        self.act_width.setText(tr("fit_width"))
        self.act_fit.setText(tr("fit_page"))
        self.act_undo.setText(tr("undo"))
        self.act_redo.setText(tr("redo"))
        self.act_order.setText(tr("order_mode"))
        self.lang_label.setText(tr("language") + ": ")
        self.search_edit.setPlaceholderText(tr("search_docs"))
        self.lbl_documents.setText(tr("documents"))
        self.lbl_pages.setText(tr("pages_header"))
        self.lbl_boxes.setText(
            tr("lines_header") if self.textline_mode else tr("boxes_header"))
        self.btn_up.setText(tr("move_up"))
        self.btn_down.setText(tr("move_down"))
        self.btn_edit.setText(tr("edit_btn"))
        self.btn_del.setText(tr("delete"))
        self.update_source_label()
        self.statusBar().showMessage(tr("help"))

    def update_source_label(self):
        self.gt_label.setText(
            tr("showing_gt") if self._src_state == "gt"
            else tr("showing_res"))

    # ---- root / documents / pages --------------------------------------

    def choose_root(self):
        d = QFileDialog.getExistingDirectory(
            self, tr("choose_root_title"),
            str(self.root) if self.root else DEFAULT_ROOT)
        if d:
            self.set_root(Path(d))

    def set_root(self, root: Path):
        self.root = root
        self.doc_list.clear()
        self.page_list.clear()
        try:
            docs = sorted(
                [d for d in root.iterdir()
                 if d.is_dir() and (d / "bbox_res").is_dir()],
                key=lambda p: p.name)
        except OSError as e:
            QMessageBox.warning(self, tr("err_title"),
                                tr("cannot_open_folder", e=e))
            return
        for d in docs:
            self.doc_list.addItem(QListWidgetItem(d.name))
        self.setWindowTitle(f"{tr('app_title')} — {root}")
        self.statusBar().showMessage(tr("loaded_docs", n=len(docs)))
        if docs:
            self.doc_list.setCurrentRow(0)

    def filter_docs(self, text: str):
        text = text.lower()
        for i in range(self.doc_list.count()):
            item = self.doc_list.item(i)
            item.setHidden(text not in item.text().lower())

    def on_doc_changed(self, current, _prev=None):
        if current is None or self.root is None:
            return
        self.doc_dir = self.root / current.text()
        self.page_list.clear()
        try:
            pages = sorted((self.doc_dir / "bbox_res").glob("*.txt"),
                           key=lambda p: p.name)
        except OSError:
            pages = []
        gt_dir = self.doc_dir / "bbox_gt"
        for p in pages:
            it = QListWidgetItem(p.name)
            if (gt_dir / p.name).exists():
                it.setText("✓ " + p.name)
            self.page_list.addItem(it)
        if pages:
            self.page_list.setCurrentRow(0)
        else:
            self.scene.clear()
            self.items = []
            self.boxes = []
            self.box_list.clear()

    def on_page_changed(self, current, _prev=None):
        if current is None or self.doc_dir is None:
            return
        self.txt_name = current.text().replace("✓ ", "")
        self.load_page()

    def step_page(self, delta: int):
        row = self.page_list.currentRow() + delta
        if 0 <= row < self.page_list.count():
            self.page_list.setCurrentRow(row)

    def _open_single(self):
        self.doc_dir = None
        self.txt_name = self.single_res.name
        self.setWindowTitle(f"{tr('app_title')} — {self.single_gt.name}")
        if not self.single_res.exists():
            QMessageBox.warning(
                self, tr("err_title"),
                tr("cannot_open_folder", e=self.single_res))
        self.load_page()

    def _open_textline(self):
        self.doc_dir = None
        self.txt_name = self.textline_src.name
        self.setWindowTitle(
            f"{tr('textline_title')} — {self.textline_src.name}")
        if not self.textline_src.exists():
            QMessageBox.warning(
                self, tr("err_title"),
                tr("cannot_open_folder", e=self.textline_src))
        self.load_page()

    def box_color(self, box: BBox) -> QColor:
        """Colour for a box: per-line colour in text-line mode, else by
        category."""
        if self.textline_mode:
            return line_color(box.category)
        return category_color(box.category)

    def load_page(self):
        if self.order_mode:
            self.order_mode = False
            self.order_seq = []
            self._set_order_checked(False)
        if self.textline_mode:
            gt_path = self.textline_gt
            res_path = self.textline_src
            # lines_gt is the editable copy of lines_res: if it does not
            # exist yet, seed it from lines_res so gt always carries res's
            # content and edits accumulate into gt. (Never overwrites an
            # existing gt, so a previous session is resumed.)
            if not gt_path.exists() and res_path.exists():
                try:
                    gt_path.parent.mkdir(parents=True, exist_ok=True)
                    gt_path.write_text(
                        res_path.read_text(encoding="utf-8", errors="ignore"),
                        encoding="utf-8")
                except OSError as e:
                    QMessageBox.warning(self, tr("save_err_title"),
                                        tr("save_err_body", e=e))
            src = gt_path if gt_path.exists() else res_path
            self.boxes = load_lines(src)
            self._src_state = "gt" if src == gt_path else "res"
        else:
            if self.single_mode:
                gt_path = self.single_gt
                res_path = self.single_res
            else:
                gt_path = self.doc_dir / "bbox_gt" / self.txt_name
                res_path = self.doc_dir / "bbox_res" / self.txt_name
            src = gt_path if gt_path.exists() else res_path
            self.boxes = load_boxes(src)
            self._src_state = "gt" if src == gt_path else "res"
        self._undo.clear()
        self._redo.clear()
        self.update_source_label()
        self.rebuild_scene(first_load=True)

    # ---- scene ----------------------------------------------------------

    def rebuild_scene(self, first_load: bool = False):
        sel = self.selected_index()
        self.scene.clear()
        self.items = []

        stem = Path(self.txt_name).stem if self.txt_name else ""
        pix = None
        if self.textline_mode:
            img = (self.textline_image
                   if self.textline_image and self.textline_image.exists()
                   else None)
        elif self.single_mode:
            img = (self.single_image
                   if self.single_image and self.single_image.exists()
                   else None)
        elif self.doc_dir and stem:
            img = find_page_image(self.doc_dir, stem)
        else:
            img = None
        if img:
            pm = QPixmap(str(img))
            if not pm.isNull():
                pix = pm
        if pix:
            self.scene.addPixmap(pix).setZValue(0)
            w, h = pix.width(), pix.height()
        else:
            w = max([b.bounding()[2] for b in self.boxes],
                    default=2000) + 100
            h = max([b.bounding()[3] for b in self.boxes],
                    default=2800) + 100
            bg = self.scene.addRect(0, 0, w, h, QPen(Qt.NoPen),
                                    QBrush(QColor("#f4f1e8")))
            bg.setZValue(0)
        self.page_rect = QRectF(0, 0, w, h)
        self.scene.setSceneRect(-20, -20, w + 40, h + 40)
        self.label_px = max(16.0, h * 0.013)

        for i, b in enumerate(self.boxes):
            item = BoxItem(self, i, b, self.label_px)
            self.scene.addItem(item)
            self.items.append(item)

        self.refresh_box_list(sel)
        if first_load:
            self._request_fit_width()

    def _request_fit_width(self):
        """Apply Fit Width now and again after layout settles, so the very
        first page (loaded before the window is shown) is fitted to the real
        viewport width rather than a placeholder size."""
        self.fit_width()
        QTimer.singleShot(0, self.fit_width)

    def refresh_box_list(self, select: int | None = None):
        self._syncing = True
        self.box_list.clear()
        for i, b in enumerate(self.boxes):
            if self.textline_mode:
                it = QListWidgetItem(tr("line_n", n=i + 1))
                it.setForeground(line_color(b.category))
                it.setToolTip(f"{len(b.points)} points")
            else:
                it = QListWidgetItem(f"{i + 1}.  {category_name(b.category)}")
                it.setForeground(category_color(b.category))
                it.setToolTip(f"category {b.category} "
                              f"({category_name(b.category)}), "
                              f"{len(b.points)} points")
            self.box_list.addItem(it)
        if select is not None and 0 <= select < self.box_list.count():
            self.box_list.setCurrentRow(select)
            if select < len(self.items):
                self.items[select].setSelected(True)
        self._syncing = False

    def fit_view(self):
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        self.scene.update()

    def fit_width(self):
        vp = self.view.viewport()
        if self.page_rect.width() <= 0 or vp.width() <= 0:
            return
        scale = (vp.width() * 0.97) / self.page_rect.width()
        self.view.resetTransform()
        self.view.scale(scale, scale)
        self.view.centerOn(self.page_rect.center().x(),
                           self.page_rect.top())
        self.view.verticalScrollBar().setValue(
            self.view.verticalScrollBar().minimum())
        self.scene.update()

    # ---- selection ------------------------------------------------------

    def selected_index(self) -> int:
        return self.box_list.currentRow()

    def has_selection(self) -> bool:
        return 0 <= self.box_list.currentRow() < len(self.boxes)

    def _apply_selection_emphasis(self, index: int):
        """Raise the selected box above the others and repaint so the
        others dim and hide their labels."""
        for i, it in enumerate(self.items):
            it.setZValue(20 if i == index else 10)
        self.scene.update()

    def select_box(self, index: int, from_scene: bool = False):
        if self._syncing:
            return
        self._syncing = True
        for i, it in enumerate(self.items):
            it.setSelected(i == index)
        if 0 <= index < self.box_list.count():
            self.box_list.setCurrentRow(index)
        self._syncing = False
        self._apply_selection_emphasis(index)

    def on_box_row_changed(self, row: int):
        if self._syncing or row < 0:
            return
        self._syncing = True
        for i, it in enumerate(self.items):
            it.setSelected(i == row)
        if 0 <= row < len(self.items):
            self.view.ensureVisible(self.items[row], 80, 80)
        self._syncing = False
        self._apply_selection_emphasis(row)

    # ---- undo / redo ----------------------------------------------------

    def _snapshot(self) -> list[BBox]:
        """Deep copy of the current boxes (category + points)."""
        return [BBox(b.category, list(b.points)) for b in self.boxes]

    def push_undo(self):
        """Record the current state before a change; clears the redo stack."""
        self._undo.append(self._snapshot())
        if len(self._undo) > self._undo_limit:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self):
        if not self._undo:
            self.statusBar().showMessage(tr("undo_empty"), 3000)
            return
        self._redo.append(self._snapshot())
        self.boxes = self._undo.pop()
        self.rebuild_scene()
        self._save_only()
        self.statusBar().showMessage(tr("undo_done"), 3000)

    def redo(self):
        if not self._redo:
            self.statusBar().showMessage(tr("redo_empty"), 3000)
            return
        self._undo.append(self._snapshot())
        self.boxes = self._redo.pop()
        self.rebuild_scene()
        self._save_only()
        self.statusBar().showMessage(tr("redo_done"), 3000)

    def _save_only(self):
        """Write the current boxes to gt without touching undo/redo."""
        if self.textline_mode:
            gt_path = self.textline_gt
        elif self.single_mode:
            gt_path = self.single_gt
        else:
            if self.doc_dir is None or self.txt_name is None:
                return
            gt_path = self.doc_dir / "bbox_gt" / self.txt_name
        try:
            (save_lines if self.textline_mode else save_boxes)(
                gt_path, self.boxes)
        except OSError as e:
            QMessageBox.warning(self, tr("save_err_title"),
                                tr("save_err_body", e=e))
            return
        self._src_state = "gt"
        self.update_source_label()
        if not self.single_mode and not self.textline_mode:
            row = self.page_list.currentRow()
            if row >= 0:
                it = self.page_list.item(row)
                if not it.text().startswith("✓"):
                    it.setText("✓ " + it.text())

    # ---- reading-order mode --------------------------------------------

    def on_order_toggled(self, on: bool):
        if self._suppress_order_toggle:
            return
        if on:
            self.enter_order_mode()
        else:
            self.cancel_order_mode()

    def enter_order_mode(self):
        if not self.boxes:
            self._set_order_checked(False)
            return
        start = 1
        if self.has_selection():
            sel = self.selected_index()
            val, ok = QInputDialog.getInt(
                self, tr("order_start_title"), tr("order_start_prompt"),
                sel + 1, 1, len(self.boxes))
            if not ok:
                self._set_order_checked(False)
                return
            start = val
        self.act_add.setChecked(False)
        self.clear_selection()
        self.order_mode = True
        self.order_start = start
        self.order_seq = []
        self.view.set_add_mode(False)
        self.view.setCursor(Qt.PointingHandCursor)
        self._update_order_status()
        self.scene.update()

    def cancel_order_mode(self):
        if not self.order_mode:
            self._set_order_checked(False)
            return
        self.order_mode = False
        self.order_seq = []
        self.view.setCursor(Qt.OpenHandCursor)
        self._set_order_checked(False)
        self.scene.update()
        self.statusBar().showMessage(tr("order_cancelled"), 3000)

    def commit_order_mode(self):
        if not self.order_mode:
            return
        seq = list(self.order_seq)
        self.order_mode = False
        if seq:
            self.push_undo()
            clicked = {id(b) for b in seq}
            rest = [b for b in self.boxes if id(b) not in clicked]
            idx = min(max(self.order_start - 1, 0), len(rest))
            self.boxes = rest[:idx] + seq + rest[idx:]
            self.rebuild_scene()
            self.autosave()
        self.order_seq = []
        self.view.setCursor(Qt.OpenHandCursor)
        self._set_order_checked(False)
        self.scene.update()
        self.statusBar().showMessage(tr("order_saved"), 3000)

    def _set_order_checked(self, value: bool):
        self._suppress_order_toggle = True
        self.act_order.setChecked(value)
        self._suppress_order_toggle = False

    def order_click(self, index: int):
        """Toggle a box into / out of the click sequence."""
        if not self.order_mode or not (0 <= index < len(self.boxes)):
            return
        b = self.boxes[index]
        pos = next((i for i, x in enumerate(self.order_seq) if x is b), None)
        if pos is not None:
            self.order_seq.pop(pos)
        else:
            self.order_seq.append(b)
        self._update_order_status()
        self.scene.update()

    def order_number_of(self, box: BBox):
        """The number that will be assigned to a box, or None if not picked."""
        for i, b in enumerate(self.order_seq):
            if b is box:
                return self.order_start + i
        return None

    def _update_order_status(self):
        k = len(self.order_seq)
        nxt = self.order_start + k
        self.statusBar().showMessage(
            tr("order_help") + "   —   " +
            tr("order_progress", k=k, n=len(self.boxes), next=nxt))

    # ---- editing --------------------------------------------------------

    def autosave(self):
        if self.textline_mode:
            gt_path = self.textline_gt
        elif self.single_mode:
            gt_path = self.single_gt
        else:
            if self.doc_dir is None or self.txt_name is None:
                return
            gt_path = self.doc_dir / "bbox_gt" / self.txt_name
        try:
            (save_lines if self.textline_mode else save_boxes)(
                gt_path, self.boxes)
        except OSError as e:
            QMessageBox.warning(self, tr("save_err_title"),
                                tr("save_err_body", e=e))
            return
        self._src_state = "gt"
        self.update_source_label()
        if not self.single_mode and not self.textline_mode:
            row = self.page_list.currentRow()
            if row >= 0:
                it = self.page_list.item(row)
                if not it.text().startswith("✓"):
                    it.setText("✓ " + it.text())
        self.statusBar().showMessage(tr("saved_msg", path=gt_path), 4000)

    def box_geometry_changed(self, index: int):
        self.refresh_box_list(index)
        self.autosave()

    def toggle_add_mode(self, on: bool):
        if on and self.order_mode:
            self.cancel_order_mode()
        self.view.set_add_mode(on)
        if on:
            self.statusBar().showMessage(tr("add_mode_msg"))

    def add_box_from_rect(self, rect: QRectF):
        n = len(self.boxes)
        dlg = BoxDialog(self, tr("dlg_add_title"), n, category=0,
                        order=n + 1, allow_order_n_plus_1=True,
                        show_category=not self.textline_mode)
        if dlg.exec() != QDialog.Accepted:
            return
        cat, order = dlg.values()
        if self.textline_mode:
            # assign a fresh, unused colour id so the new line is distinct
            cat = (max((b.category for b in self.boxes), default=-1) + 1)
        self.push_undo()
        pts = [(rect.left(), rect.top()), (rect.right(), rect.top()),
               (rect.right(), rect.bottom()), (rect.left(), rect.bottom())]
        b = BBox(cat, pts)
        b.normalize()
        self.boxes.insert(order - 1, b)
        self.act_add.setChecked(False)
        self.rebuild_scene()
        self.select_box(order - 1)
        self.autosave()

    def delete_selected(self):
        self.delete_box(self.selected_index())

    def delete_box(self, idx: int):
        if idx is None or idx < 0 or idx >= len(self.boxes):
            return
        b = self.boxes[idx]
        name = (tr("line_n", n=idx + 1) if self.textline_mode
                else category_name(b.category))
        ret = QMessageBox.question(
            self, tr("del_title"),
            tr("del_body", i=idx + 1, name=name))
        if ret != QMessageBox.Yes:
            return
        self.push_undo()
        self.boxes.pop(idx)
        self.rebuild_scene()
        if self.boxes:
            self.select_box(min(idx, len(self.boxes) - 1))
        self.autosave()

    def move_selected(self, delta: int):
        idx = self.selected_index()
        new = idx + delta
        if idx < 0 or not (0 <= new < len(self.boxes)):
            return
        self.push_undo()
        self.boxes.insert(new, self.boxes.pop(idx))
        self.rebuild_scene()
        self.select_box(new)
        self.autosave()

    def edit_box_dialog(self, index: int):
        if index is None or index < 0 or index >= len(self.boxes):
            return
        b = self.boxes[index]
        dlg = BoxDialog(self, tr("dlg_edit_title"), len(self.boxes),
                        category=b.category, order=index + 1,
                        show_category=not self.textline_mode)
        if dlg.exec() != QDialog.Accepted:
            return
        cat, order = dlg.values()
        self.push_undo()
        if not self.textline_mode:
            b.category = cat   # keep the stable colour id in text-line mode
        new = order - 1
        if new != index:
            self.boxes.insert(new, self.boxes.pop(index))
        self.rebuild_scene()
        self.select_box(new)
        self.autosave()

    def clear_selection(self):
        """Return to the 'nothing selected' state: deselect all, reset z,
        and repaint so every box renders normally again."""
        self._syncing = True
        for it in self.items:
            it.setSelected(False)
            it.setZValue(10)
        self.box_list.setCurrentRow(-1)
        self.box_list.clearSelection()
        self._syncing = False
        self.scene.update()

    # ---- keyboard -------------------------------------------------------

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_did_initial_fit", False) and self.boxes:
            self._did_initial_fit = True
            # Defer until the layout has the final viewport size.
            QTimer.singleShot(0, self.fit_width)

    def keyPressEvent(self, event):
        # WASD / arrow keys pan the image. Skip while typing in a text field,
        # and skip arrows while a list has focus (so list navigation still
        # works); WASD always pans otherwise.
        fw = self.focusWidget()
        if not isinstance(fw, QLineEdit):
            d = CanvasView.PAN_KEYS.get(event.key())
            is_arrow = event.key() in (Qt.Key_Up, Qt.Key_Down,
                                       Qt.Key_Left, Qt.Key_Right)
            if d is not None and not (is_arrow and isinstance(fw, QListWidget)):
                step = 220 if (event.modifiers() & Qt.ShiftModifier) else 90
                self.view.pan_by(d[0] * step, d[1] * step)
                event.accept()
                return

        if self.order_mode:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.commit_order_mode()
                return
            if event.key() == Qt.Key_Escape:
                self.cancel_order_mode()
                return
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key_Escape:
            if self.act_add.isChecked():
                self.act_add.setChecked(False)
            else:
                self.clear_selection()
            return
        super().keyPressEvent(event)


# ----------------------------------------------------------------------------

def main():
    # Large page scans can exceed Qt's default 256 MB image allocation cap,
    # which makes QImageReader reject them. Disable the limit (0 = no limit)
    # so images load at their full, original resolution.
    QImageReader.setAllocationLimit(0)

    parser = argparse.ArgumentParser(
        description="PHAROS BBox Editor. With the three arguments below it "
                    "edits a single page; with no arguments it opens the "
                    "folder browser for the whole dataset.")
    parser.add_argument("--image", metavar="FILE",
                        help="Page image file (e.g. ...\\pages\\0000.jpg)")
    parser.add_argument("--box_res", "--bbox_res", dest="box_res",
                        metavar="FILE",
                        help="Model output txt (read-only, never modified)")
    parser.add_argument("--bbox_gt", dest="bbox_gt", metavar="FILE",
                        help="Corrected output txt (edits are written here)")
    parser.add_argument("--lines_res", "--lines", "--line_txt",
                        dest="lines_res", metavar="FILE",
                        help="Text-line source txt (4 points per line, no "
                             "category; read-only). Use with --image and "
                             "--lines_gt for the Text Line corrector.")
    parser.add_argument("--lines_gt", dest="lines_gt", metavar="FILE",
                        help="Corrected text-line output txt "
                             "(edits are written here).")
    args, _ = parser.parse_known_args()

    given = [args.image, args.box_res, args.bbox_gt]
    n_given = sum(x is not None for x in given)
    has_lines = bool(args.lines_res or args.lines_gt)

    app = QApplication(sys.argv)
    app.setApplicationName("PHAROS BBox Editor")

    if (args.image and args.lines_res and args.lines_gt
            and not args.box_res and not args.bbox_gt):
        # Text Line Bounding Box & Reading Order corrector
        # (image + lines_res + lines_gt). lines_res is read-only;
        # edits are written to lines_gt.
        win = MainWindow(textline=(Path(args.image),
                                   Path(args.lines_res),
                                   Path(args.lines_gt)))
    elif n_given == 3 and not has_lines:
        single = (Path(args.image), Path(args.box_res), Path(args.bbox_gt))
        win = MainWindow(single=single)
    elif n_given == 0 and not has_lines:
        win = MainWindow()
    else:
        print("Use one of:\n"
              "  (no arguments)                       -> folder browser\n"
              "  --image --box_res --bbox_gt          -> single bbox page\n"
              "  --image --lines_res --lines_gt       -> text-line corrector",
              file=sys.stderr)
        sys.exit(2)

    win.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
