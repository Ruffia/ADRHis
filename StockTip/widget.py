# -*- coding: utf-8 -*-
"""StockTip 主窗口：DC / XQ 背离结果 + 市场温度 + 关注名单 + 资金流向（正红负绿）。"""

import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QObject, QDate, QEvent, QMargins, QTimer
from PySide6.QtGui import (
    QBrush, QColor, QCursor, QPalette, QPainter, QShortcut, QKeySequence,
    QStandardItem, QStandardItemModel,
)
from PySide6.QtSql import QSqlDatabase, QSqlQuery, QSqlQueryModel
from PySide6.QtWidgets import (
    QApplication, QWidget, QDialog, QDialogButtonBox, QInputDialog, QLabel,
    QLineEdit, QMenu, QMessageBox, QHeaderView, QAbstractItemView,
    QSplitter, QTableView, QTabWidget, QTextEdit, QToolTip, QVBoxLayout,
    QStyledItemDelegate, QStyle,
)
from PySide6.QtCharts import (
    QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView,
    QStackedBarSeries, QValueAxis,
)

from ui_form import Ui_m_MainUI

# ----------------------------- 配置 -----------------------------
DB_PATH = Path(r"U:\Grab\Tip.db")
WRITE_CONNECTION = "stocktip_write"

READ_OPTIONS = "QSQLITE_OPEN_READONLY;QSQLITE_BUSY_TIMEOUT=15000"
WRITE_OPTIONS = "QSQLITE_BUSY_TIMEOUT=15000"

MONEY_COL = "主力净流入"
RISE_COL = "涨跌幅"
RISE_COL_SHORT = "涨幅"
CODE_COL_TITLE = "股票代码"
NAME_COL_TITLE = "名称"
ROW_NO_TITLE = "行号"
DETAIL_DAYS = 30

# 净流向着色阈值（正负对称），单位与数据一致（万元）
FLOW_LIGHT = 500.0
FLOW_MEDIUM = 1000.0
FLOW_STRONG = 2000.0

CHART_TABLE = "IndividualFundFlow_DC"
RATIO_DAYS = 40
LIMIT_DAYS = 30
RATIO_Y_STEP = 10.0
LIMIT_Y_MAX = 260.0
LIMIT_Y_STEP = 20.0
MARKET_TAB_TITLE = "Market Temperature"
FOCUS_TAB_TITLE = "Focus Stock"

DC_TABLE = "IndividualFundFlow_DC"
XQ_TABLE = "IndividualFundFlow_XQ"

RATIO_BUCKETS = [
    ("< 10%",     lambda v: v < 10.0,                    "#1B5E20"),
    ("10 ~ 30%",  lambda v: 10.0 <= v < 30.0,            "#2E7D32"),
    ("30 ~ 45%",  lambda v: 30.0 <= v < 45.0,            "#A5D6A7"),
    ("45 ~ 55%",  lambda v: 45.0 <= v < 55.0,            "#EF9A9A"),
    ("55 ~ 65%",  lambda v: 55.0 <= v < 65.0,            "#E53935"),
    (">= 65%",    lambda v: v >= 65.0,                   "#B71C1C"),
]

ALLOWED_TABLES = (DC_TABLE, XQ_TABLE)

# 代码归一化：'SZ000441' / '000441.sz' → '000441'
CODE_NORM = (
    "replace(replace(replace(replace(upper(CAST({col} AS TEXT)), '.', ''), 'SZ', ''), 'SH', ''), 'BJ', '')"
)


def _norm(col: str) -> str:
    return CODE_NORM.format(col=col)


FUND_FLOW_SQL_TEMPLATE = r"""
WITH cal AS (
    SELECT "TradeDate", ROW_NUMBER() OVER (ORDER BY "TradeDate") AS dno
    FROM (SELECT DISTINCT "TradeDate" FROM "{table}")
),
seqd AS (
    SELECT
        f."TradeDate", f."StockCode", f."StockName", f."Price", f."Rise",
        f."FundFlow_MainForce",
        c.dno AS mkt_dno,
        ROW_NUMBER() OVER (PARTITION BY f."StockCode" ORDER BY f."TradeDate") AS seq
    FROM "{table}" f
    JOIN cal c ON c."TradeDate" = f."TradeDate"
),
tagged AS (
    SELECT
        *,
        MAX(CASE WHEN "Rise" >= 9.8 THEN seq END)
            OVER (PARTITION BY "StockCode") AS lu_seq,
        MAX(CASE WHEN "Rise" >= 9.8 THEN mkt_dno END)
            OVER (PARTITION BY "StockCode") AS lu_mkt_dno,
        MAX(CASE WHEN "Rise" >= 9.8 THEN "TradeDate" END)
            OVER (PARTITION BY "StockCode") AS lu_date
    FROM seqd
),
hits AS (
    SELECT * FROM tagged
    WHERE lu_seq IS NOT NULL
      AND seq > lu_seq
      AND seq - lu_seq <= 10
      AND "Rise" < 0
      AND "FundFlow_MainForce" > 0
      AND lu_mkt_dno >= (SELECT MAX(dno) FROM cal) - 10
)
SELECT
    ROW_NUMBER() OVER (ORDER BY "StockCode", "TradeDate") AS "行号",
    "StockCode"          AS "股票代码",
    "StockName"          AS "名称",
    lu_date              AS "最近涨停日",
    "TradeDate"          AS "背离日",
    seq - lu_seq         AS "涨停后第几天",
    "Rise"               AS "涨跌幅(%)",
    "Price"              AS "最新价",
    "FundFlow_MainForce" AS "主力净流入(万元)",
    COUNT(*) OVER (PARTITION BY "StockCode") AS "该股背离次数"
FROM hits
WHERE Price < 40.0
ORDER BY "StockCode", "TradeDate";
"""

DETAIL_SQL = {
    DC_TABLE: """
        SELECT
            "TradeDate"                AS "交易日",
            "StockCode"                AS "股票代码",
            "StockName"                AS "名称",
            "Price"                    AS "收盘价",
            "Rise"                     AS "涨跌幅(%)",
            "FundFlow_MainForce"       AS "主力净流入(万元)",
            "FundFlow_SuperLargeOrder" AS "超大单净流入(万元)",
            "FundFlow_LargeOrder"      AS "大单净流入(万元)",
            "FundFlow_MediumOrder"     AS "中单净流入(万元)",
            "FundFlow_SmallOrder"      AS "小单净流入(万元)"
        FROM "IndividualFundFlow_DC"
        WHERE {code_norm} = {code}
        ORDER BY "TradeDate" DESC
        LIMIT {limit};
    """,
    XQ_TABLE: """
        SELECT
            "TradeDate"          AS "交易日",
            "StockCode"          AS "股票代码",
            "StockName"          AS "名称",
            "Price"              AS "收盘价",
            "Rise"               AS "涨跌幅(%)",
            "FundFlow_MainForce" AS "主力净流入(万元)"
        FROM "IndividualFundFlow_XQ"
        WHERE {code_norm} = {code}
        ORDER BY "TradeDate" DESC
        LIMIT {limit};
    """,
}

INSERT_FOCUS_SQL = """
INSERT OR IGNORE INTO "FocusStock"
    ("FocusDate", "StockCode", "StockName", "FocusType")
VALUES (?, ?, ?, 0);
"""

DELETE_FOCUS_SQL = """DELETE FROM "FocusStock" WHERE rowid = ?;"""

UPDATE_FOCUS_TYPE_SQL = """UPDATE "FocusStock" SET "FocusType" = ? WHERE rowid = ?;"""

INSERT_COMMENT_SQL = """
INSERT INTO "FocusStockComment" ("CommentDate", "StockCode", "StockName", "Comment")
VALUES (?, ?, ?, ?);
"""

UPDATE_COMMENT_SQL = """UPDATE "FocusStockComment" SET "Comment" = ? WHERE rowid = ?;"""

STOCK_ROWS_SQL = """
SELECT "TradeDate", "StockCode", "StockName", "Price", "Rise", "FundFlow_MainForce"
FROM "{table}"
WHERE "StockCode" {op} ?
ORDER BY "TradeDate";
"""

RATIO_SQL_TEMPLATE = """
SELECT
    "TradeDate",
    SUM(CASE WHEN "Rise" >= 0.0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) AS ratio
FROM "{table}"
GROUP BY "TradeDate"
ORDER BY "TradeDate" DESC
LIMIT {limit};
"""

LIMIT_SQL_TEMPLATE = """
SELECT
    "TradeDate",
    SUM(CASE WHEN "Rise" > 9.8  THEN 1 ELSE 0 END) AS up_cnt,
    SUM(CASE WHEN "Rise" < -9.8 THEN 1 ELSE 0 END) AS down_cnt
FROM "{table}"
GROUP BY "TradeDate"
ORDER BY "TradeDate" DESC
LIMIT {limit};
"""


# ------------------------- 工具 -------------------------
def _sql_quote(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _code_core(code) -> str:
    """'SZ000441' / '000441.sz' / '000441' → '000441'。"""
    return "".join(ch for ch in str(code).upper() if ch.isdigit())


def _code_candidates(code) -> list[str]:
    raw = str(code).strip()
    digits = _code_core(raw)
    upper = raw.upper()

    cands = [raw]
    if digits:
        cands.append(digits)
    for mk in ("SZ", "SH", "BJ"):
        if upper.startswith(mk) and digits:
            cands.append(f"{digits}.{mk}")
        if upper.endswith(mk) and digits:
            cands.append(f"{mk}{digits}")

    seen, out = set(), []
    for cand in cands:
        if cand and cand not in seen:
            seen.add(cand)
            out.append(cand)
    return out


def _is_locked_error(text: str) -> bool:
    t = (text or "").lower()
    return "locked" in t or "busy" in t


def _query_rows(db: QSqlDatabase, sql: str) -> list[list]:
    query = QSqlQuery(db)
    query.setForwardOnly(True)
    rows: list[list] = []
    try:
        if not query.exec(sql):
            err = query.lastError()
            raise RuntimeError(f"{err.text()}\nSQL: {' '.join(sql.split())}")
        col_count = query.record().count()
        while query.next():
            rows.append([query.value(i) for i in range(col_count)])
    finally:
        query.finish()
    return rows


def _query_bound(db: QSqlDatabase, sql: str, params: list) -> list[list]:
    query = QSqlQuery(db)
    query.setForwardOnly(True)
    rows: list[list] = []
    try:
        query.prepare(sql)
        for value in params:
            query.addBindValue(value)
        if not query.exec():
            raise RuntimeError(query.lastError().text())
        col_count = query.record().count()
        while query.next():
            rows.append([query.value(i) for i in range(col_count)])
    finally:
        query.finish()
    return rows


def _load_stock_rows(db: QSqlDatabase, table: str, code: str) -> list[list]:
    for cand in _code_candidates(code):
        rows = _query_bound(db, STOCK_ROWS_SQL.format(table=table, op="="), [cand])
        if rows:
            return rows

    digits = _code_core(code)
    if digits:
        return _query_bound(db, STOCK_ROWS_SQL.format(table=table, op="LIKE"),
                            [f"%{digits}%"])
    return []


def _merge_flow(dc_rows: list[list], xq_rows: list[list], code: str):
    dc_map = {str(r[0])[:10]: r for r in dc_rows if r[0] is not None}
    xq_map = {str(r[0])[:10]: r for r in xq_rows if r[0] is not None}

    dates = sorted(set(dc_map) | set(xq_map), reverse=True)
    merged = []
    matched = 0
    for date in dates:
        dc_row = dc_map.get(date)
        xq_row = xq_map.get(date)
        if dc_row is not None and xq_row is not None:
            matched += 1
        merged.append((
            date,
            dc_row[1] if dc_row else (xq_row[1] if xq_row else code),
            dc_row[2] if dc_row else (xq_row[2] if xq_row else ""),
            dc_row[3] if dc_row else None,          # 收盘价
            dc_row[4] if dc_row else None,          # 涨幅
            xq_row[5] if xq_row else None,          # 主力净流入XQ
            dc_row[5] if dc_row else None,          # 主力净流入DC
        ))
    return merged, len(dc_map), len(xq_map), matched


def _sparse_labels(labels: list[str], step: int = 2) -> list[str]:
    return [lab if i % step == 0 else "" for i, lab in enumerate(labels)]


def _configure_date_axis(axis: QBarCategoryAxis, labels: list[str],
                         angle: int = -90) -> None:
    if hasattr(axis, "setLabelsAngle"):
        axis.setLabelsAngle(angle)
        axis.append(labels)
    else:
        axis.append(_sparse_labels(labels))


# ------------------------- 颜色规则 -------------------------
def money_flow_color(v: float):
    """主力净流入：正值三档红、负值三档绿，阈值对称。"""
    if v > FLOW_STRONG:                       # > 2000 万元
        return "#C62828", "#FFFFFF"           # 深红
    if v > FLOW_MEDIUM:                       # 1000 ~ 2000
        return "#E57373", "#FFFFFF"           # 中红
    if v > FLOW_LIGHT:                        # 500 ~ 1000
        return "#FFCDD2", "#8B0000"           # 浅红

    if v < -FLOW_STRONG:                      # < -2000 万元
        return "#1B5E20", "#FFFFFF"           # 深绿
    if v < -FLOW_MEDIUM:                      # -2000 ~ -1000
        return "#43A047", "#FFFFFF"           # 中绿
    if v < -FLOW_LIGHT:                       # -1000 ~ -500
        return "#C8E6C9", "#1B5E20"           # 浅绿

    return None                               # -500 ~ 500 不着色


def rise_color(v: float):
    if v < -8:
        return "#2E7D32", "#FFFFFF"
    if v < -5:
        return "#81C784", "#1B5E20"
    if v < -3:
        return "#C8E6C9", "#1B5E20"
    return None


# ------------------------- 列宽 -------------------------
def fit_view_to_width(view: QTableView, min_col: int = 90, max_col: int = 320,
                      padding: int = 24, sample_rows: int = 50) -> None:
    model = view.model()
    if model is None or model.columnCount() == 0:
        return

    cols = [c for c in range(model.columnCount()) if not view.isColumnHidden(c)]
    if not cols:
        return

    body_fm = view.fontMetrics()
    head_fm = view.horizontalHeader().fontMetrics()
    rows = min(max(model.rowCount(), 0), sample_rows)

    widths = []
    for col in cols:
        title = str(model.headerData(
            col, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) or "")
        w = head_fm.horizontalAdvance(title) + padding
        for row in range(rows):
            txt = model.index(row, col).data(Qt.ItemDataRole.DisplayRole)
            if txt is None or txt == "":
                continue
            w = max(w, body_fm.horizontalAdvance(str(txt)) + 16)
        widths.append(int(max(min_col, min(w, max_col))))

    avail = view.viewport().width() - 2
    if avail <= 0:
        return
    avail = max(avail, len(cols) * min_col)

    total = sum(widths)
    if total < avail:
        extra = avail - total
        widths = [w + int(extra * w / total) for w in widths]
        widths[-1] += avail - sum(widths)
    elif total > avail:
        scale = avail / total
        widths = [max(min_col, int(w * scale)) for w in widths]
        overflow = sum(widths) - avail
        for i in sorted(range(len(widths)), key=lambda k: widths[k], reverse=True):
            if overflow <= 0:
                break
            cut = min(overflow, widths[i] - min_col)
            widths[i] -= cut
            overflow -= cut

    for col, w in zip(cols, widths):
        view.setColumnWidth(col, w)


def fit_columns(view: QTableView, min_col: int = 80, max_col: int = 220,
                padding: int = 24, sample_rows: int = 50):
    model = view.model()
    if model is None or model.columnCount() == 0:
        return

    body_fm = view.fontMetrics()
    head_fm = view.horizontalHeader().fontMetrics()
    rows = min(max(model.rowCount(), 0), sample_rows)

    widths = []
    for col in range(model.columnCount()):
        title = str(model.headerData(
            col, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) or "")
        w = head_fm.horizontalAdvance(title) + padding
        for row in range(rows):
            txt = model.index(row, col).data(Qt.ItemDataRole.DisplayRole)
            if txt is None or txt == "":
                continue
            w = max(w, body_fm.horizontalAdvance(str(txt)) + 16)
        widths.append(int(max(min_col, min(w, max_col))))

    avail = view.viewport().width()
    total = sum(widths)
    if avail > 0 and total < avail:
        extra = avail - total
        widths = [w + int(extra * w / total) for w in widths]
        widths[-1] += avail - sum(widths)

    for col, w in enumerate(widths):
        view.setColumnWidth(col, w)


# ------------------------- 柱状图 tooltip -------------------------
def _ratio_tip_text(info) -> str:
    date, ratio = info
    return f"{date}\n上涨占比：{ratio:.1f}%"


def _limit_tip_text(info) -> str:
    date, up, down = info
    text = f"{date}\n涨停：{up} 家\n跌停：{down} 家"
    if up > LIMIT_Y_MAX or down > LIMIT_Y_MAX:
        text += f"\n\n注：超过 {int(LIMIT_Y_MAX)} 的部分已截顶显示"
    return text


def _show_tip(tips: dict, index: int, formatter):
    info = tips.get(index)
    if info is not None:
        QToolTip.showText(QCursor.pos(), formatter(info))


def _hover_tip(tips: dict, status: bool, index: int, formatter):
    if not status:
        QToolTip.hideText()
        return
    _show_tip(tips, index, formatter)


def _connect_bar_tooltip(series, tips: dict, formatter) -> None:
    for name in ("clicked", "barClicked"):
        signal = getattr(series, name, None)
        if signal is None:
            continue
        try:
            signal.connect(
                lambda index, barset=None, t=tips, f=formatter:
                _show_tip(t, index, f))
            break
        except (TypeError, RuntimeError):
            continue

    for name in ("hovered", "barHovered"):
        signal = getattr(series, name, None)
        if signal is None:
            continue
        try:
            signal.connect(
                lambda status, index, barset=None, t=tips, f=formatter:
                _hover_tip(t, status, index, f))
            break
        except (TypeError, RuntimeError):
            continue


# ------------------------- 市场温度图表 -------------------------
def build_ratio_chart(db: QSqlDatabase) -> QChart:
    sql = RATIO_SQL_TEMPLATE.format(table=CHART_TABLE, limit=int(RATIO_DAYS))
    rows = _query_rows(db, sql)
    rows.reverse()

    chart = QChart()
    if not rows:
        chart.setTitle("暂无数据")
        return chart

    categories = [str(r[0])[5:10] for r in rows]
    values = [float(r[1] or 0.0) for r in rows]

    series = QStackedBarSeries()
    for label, predicate, color in RATIO_BUCKETS:
        bar_set = QBarSet(label)
        bar_set.setColor(QColor(color))
        bar_set.setBorderColor(QColor(color))
        bar_set.append([v if predicate(v) else 0.0 for v in values])
        series.append(bar_set)

    chart.addSeries(series)
    chart.setTitle(f"每日上涨股票占比（最近 {len(rows)} 个交易日）")
    chart.legend().setVisible(True)
    chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
    chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
    chart.setMargins(QMargins(8, 8, 8, 30))

    tips = {i: (categories[i], values[i]) for i in range(len(categories))}
    _connect_bar_tooltip(series, tips, _ratio_tip_text)

    axis_x = QBarCategoryAxis()
    _configure_date_axis(axis_x, categories, angle=-90)
    chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
    series.attachAxis(axis_x)

    axis_y = QValueAxis()
    axis_y.setRange(0.0, 100.0)
    axis_y.setLabelFormat("%.0f")
    axis_y.setTitleText("上涨占比 (%)")
    axis_y.setTickType(QValueAxis.TickType.TicksDynamic)
    axis_y.setTickAnchor(0.0)
    axis_y.setTickInterval(RATIO_Y_STEP)
    chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
    series.attachAxis(axis_y)
    return chart


def build_limit_chart(db: QSqlDatabase) -> QChart:
    sql = LIMIT_SQL_TEMPLATE.format(table=CHART_TABLE, limit=int(LIMIT_DAYS))
    rows = _query_rows(db, sql)
    rows.reverse()

    chart = QChart()
    if not rows:
        chart.setTitle("暂无数据")
        return chart

    categories = [str(r[0])[5:10] for r in rows]
    up_raw = [int(r[1] or 0) for r in rows]
    down_raw = [int(r[2] or 0) for r in rows]
    cap = int(LIMIT_Y_MAX)
    up = [min(v, cap) for v in up_raw]
    down = [min(v, cap) for v in down_raw]

    up_set = QBarSet("涨停数")
    up_set.append(up)
    up_set.setColor(QColor("#C62828"))
    up_set.setBorderColor(QColor("#8B0000"))

    down_set = QBarSet("跌停数")
    down_set.append(down)
    down_set.setColor(QColor("#2E7D32"))
    down_set.setBorderColor(QColor("#1B5E20"))

    series = QBarSeries()
    series.append(up_set)
    series.append(down_set)

    chart.addSeries(series)
    chart.setTitle(f"每日涨停 / 跌停家数（最近 {len(rows)} 个交易日）")
    chart.legend().setVisible(True)
    chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
    chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
    chart.setMargins(QMargins(8, 8, 8, 30))

    tips = {
        i: (categories[i], up_raw[i], down_raw[i])
        for i in range(len(categories))
    }
    _connect_bar_tooltip(series, tips, _limit_tip_text)

    axis_x = QBarCategoryAxis()
    _configure_date_axis(axis_x, categories, angle=-90)
    chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
    series.attachAxis(axis_x)

    axis_y = QValueAxis()
    axis_y.setRange(0.0, LIMIT_Y_MAX)
    axis_y.setLabelFormat("%d")
    axis_y.setTitleText("家数")
    axis_y.setTickType(QValueAxis.TickType.TicksDynamic)
    axis_y.setTickAnchor(0.0)
    axis_y.setTickInterval(LIMIT_Y_STEP)
    chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
    series.attachAxis(axis_y)
    return chart


# ------------------------- Ctrl+F 查找 -------------------------
class TableFinder(QObject):
    HIGHLIGHT_BG = "#1565C0"
    HIGHLIGHT_FG = "#FFFFFF"

    def __init__(self, view: QTableView, parent=None):
        super().__init__(view if parent is None else parent)
        self.view = view
        self.term = ""
        self.matches: list[int] = []
        self.index = -1

        pal = view.palette()
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            pal.setColor(group, QPalette.ColorRole.Highlight, QColor(self.HIGHLIGHT_BG))
            pal.setColor(group, QPalette.ColorRole.HighlightedText,
                         QColor(self.HIGHLIGHT_FG))
        view.setPalette(pal)

    def run(self, parent_widget):
        text, ok = QInputDialog.getText(
            parent_widget, "查找股票", "股票代码或名称：",
            QLineEdit.EchoMode.Normal, self.term)
        if not ok:
            return

        term = text.strip()
        if not term:
            return

        if term == self.term and self.matches:
            self.next_match()
            return

        self.term = term
        self._collect()
        if not self.matches:
            self.index = -1
            QToolTip.showText(QCursor.pos(), f"未找到：{term}")
            return

        self.index = 0
        self._goto(self.matches[0])
        self._notify()

    def refresh(self):
        if not self.term:
            return
        self._collect()
        if self.matches:
            self.index = min(self.index, len(self.matches) - 1)
            self._goto(self.matches[self.index])

    def _notify(self):
        QToolTip.showText(
            self.view.viewport().mapToGlobal(self.view.viewport().rect().bottomRight()),
            f"匹配 {self.index + 1}/{len(self.matches)}：{self.term}")

    def _column(self, title: str) -> int:
        model = self.view.model()
        if model is None:
            return -1
        for col in range(model.columnCount()):
            if str(model.headerData(col, Qt.Orientation.Horizontal) or "") == title:
                return col
        return -1

    def _collect(self):
        self.matches = []
        model = self.view.model()
        if model is None or not self.term:
            return

        text = self.term.lower()
        code_col = self._column(CODE_COL_TITLE)
        name_col = self._column(NAME_COL_TITLE)
        cols = [c for c in (code_col, name_col) if c >= 0]
        if not cols:
            cols = list(range(model.columnCount()))

        for row in range(model.rowCount()):
            for col in cols:
                value = model.index(row, col).data()
                if value is not None and text in str(value).lower():
                    self.matches.append(row)
                    break

    def next_match(self):
        if not self.matches:
            return
        self.index = (self.index + 1) % len(self.matches)
        self._goto(self.matches[self.index])
        self._notify()

    def _goto(self, row: int):
        model = self.view.model()
        if model is None:
            return
        col = self._column(CODE_COL_TITLE)
        if col < 0:
            col = 0
        index = model.index(row, col)
        self.view.setCurrentIndex(index)
        self.view.selectRow(row)
        self.view.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)


# ------------------------- 单元格绘制 -------------------------
class ThresholdColorDelegate(QStyledItemDelegate):
    RULES = {
        MONEY_COL: money_flow_color,
        RISE_COL: rise_color,
        RISE_COL_SHORT: rise_color,
    }

    FOCUS_FG = QColor("#9E9E9E")

    def __init__(self, parent=None, focused_codes: set[str] | None = None):
        super().__init__(parent)
        self.focused_codes = focused_codes if focused_codes is not None else set()
        self._code_col = -1

    def _code_column(self, model) -> int:
        if self._code_col < 0:
            for col in range(model.columnCount()):
                if str(model.headerData(col, Qt.Orientation.Horizontal) or "") == CODE_COL_TITLE:
                    self._code_col = col
                    break
        return self._code_col

    def _is_focused_row(self, index) -> bool:
        if not self.focused_codes:
            return False
        model = index.model()
        col = self._code_column(model)
        if col < 0:
            return False
        value = model.index(index.row(), col).data()
        if value is None:
            return False
        return _code_core(value) in self.focused_codes

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)

        option.displayAlignment = Qt.AlignmentFlag.AlignCenter

        if option.state & QStyle.StateFlag.State_Selected:
            return

        if self._is_focused_row(index):
            option.palette.setColor(QPalette.ColorRole.Text, self.FOCUS_FG)
            return

        model = index.model()
        header = model.headerData(
            index.column(), Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole
        ) or ""
        rule = next((fn for name, fn in self.RULES.items() if header.startswith(name)), None)
        if rule is None:
            return

        try:
            number = float(index.data(Qt.ItemDataRole.DisplayRole))
        except (TypeError, ValueError):
            return

        colors = rule(number)
        if colors is None:
            return

        bg, fg = colors
        option.backgroundBrush = QBrush(QColor(bg))
        option.palette.setColor(QPalette.ColorRole.Text, QColor(fg))


class FocusTypeDelegate(QStyledItemDelegate):
    IMPORTANT_BG = QColor("#FFE0B2")
    IMPORTANT_FG = QColor("#8D4E00")
    NORMAL_FG = QColor("#333333")

    def __init__(self, parent=None, type_getter=None):
        super().__init__(parent)
        self._type_getter = type_getter or (lambda index: 0)

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)

        option.displayAlignment = Qt.AlignmentFlag.AlignCenter

        if option.state & QStyle.StateFlag.State_Selected:
            return

        if self._type_getter(index) == 1:
            option.backgroundBrush = QBrush(self.IMPORTANT_BG)
            option.palette.setColor(QPalette.ColorRole.Text, self.IMPORTANT_FG)
        else:
            option.palette.setColor(QPalette.ColorRole.Text, self.NORMAL_FG)


class FundFlowQueryModel(QSqlQueryModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.error_text = ""

    def refresh(self, sql: str, db: QSqlDatabase) -> bool:
        self.setQuery(sql, db)
        err = self.lastError()
        if err.isValid():
            self.error_text = err.text()
            return False
        self.error_text = ""
        return True

    def fetch_all(self):
        guard = 0
        while self.canFetchMore() and guard < 20000:
            self.fetchMore()
            guard += 1


def apply_table_style(view: QTableView, colorize: bool = True,
                      focused_codes: set[str] | None = None):
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setAlternatingRowColors(True)
    view.setWordWrap(False)
    view.setShowGrid(False)
    view.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    view.verticalHeader().setVisible(False)
    view.verticalHeader().setDefaultSectionSize(28)

    header = view.horizontalHeader()
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
    header.setHighlightSections(False)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setStretchLastSection(False)
    header.setMinimumHeight(34)
    font = header.font()
    font.setBold(True)
    header.setFont(font)

    if colorize:
        view.setItemDelegate(ThresholdColorDelegate(view, focused_codes))


# ------------------------- 明细窗口 -------------------------
class StockDetailDialog(QDialog):
    def __init__(self, code: str, name: str, table: str, db: QSqlDatabase, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.table = table
        self.setWindowTitle(f"{code} {name} · {table} · 最近 {DETAIL_DAYS} 个交易日")
        self.resize(1240, 560)
        self._fitted = False

        self.model = QSqlQueryModel(self)
        self.view = QTableView(self)
        apply_table_style(self.view)
        self.view.setModel(self.model)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.view)

        self._load(code, db)

    def _load(self, code: str, db: QSqlDatabase):
        sql = DETAIL_SQL[self.table].format(
            code=_sql_quote(_code_core(code)),
            code_norm=_norm('"StockCode"'),
            limit=int(DETAIL_DAYS),
        )
        self.model.setQuery(sql, db)
        err = self.model.lastError()
        if err.isValid():
            QMessageBox.warning(self, "明细查询失败", err.text())
            return

        while self.model.canFetchMore():
            self.model.fetchMore()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._fitted:
            self._fitted = True
            QTimer.singleShot(0, self._fit_columns)

    def _fit_columns(self):
        fit_columns(self.view, min_col=88, max_col=200)


# ------------------------- 资金流向窗口 -------------------------
class StockFlowDialog(QDialog):
    HEADERS = [
        "交易日", "股票代码", "股票名称", "收盘价",
        "涨幅(%)", "主力净流入XQ(万元)", "主力净流入DC(万元)",
    ]

    def __init__(self, code: str, name: str, db: QSqlDatabase,
                 parent=None, cache: dict | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.code = code
        self.name = name
        self.db = db
        self._cache = cache
        self._fitted = False

        self.setWindowTitle(f"{code} {name} · 资金流向（XQ vs DC）")
        self.resize(1180, 620)

        self.model = QStandardItemModel(0, len(self.HEADERS), self)
        self.model.setHorizontalHeaderLabels(self.HEADERS)

        self.view = QTableView(self)
        apply_table_style(self.view)
        self.view.setModel(self.model)

        self.status = QLabel("正在加载…", self)
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#555; padding:2px 4px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.view)
        layout.addWidget(self.status)

    def start(self):
        QTimer.singleShot(0, self.load)

    def load(self):
        key = _code_core(self.code)

        if self._cache is not None and key in self._cache:
            merged, dc_count, xq_count, matched = self._cache[key]
            self._render(merged)
            self._set_status(dc_count, xq_count, matched)
            return

        try:
            dc_rows = _load_stock_rows(self.db, DC_TABLE, self.code)
            xq_rows = _load_stock_rows(self.db, XQ_TABLE, self.code)
        except Exception as exc:
            self.status.setText(f"查询失败：{exc}")
            return

        merged, dc_count, xq_count, matched = _merge_flow(dc_rows, xq_rows, self.code)
        if self._cache is not None:
            self._cache[key] = (merged, dc_count, xq_count, matched)

        self._render(merged)
        self._set_status(dc_count, xq_count, matched)

    def _render(self, rows: list[tuple]):
        self.model.removeRows(0, self.model.rowCount())
        for row in rows:
            items = []
            for value in row:
                item = QStandardItem()
                if value is not None:
                    item.setData(value, Qt.ItemDataRole.DisplayRole)
                item.setEditable(False)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                items.append(item)
            self.model.appendRow(items)

        if not self._fitted:
            self._fitted = True
            QTimer.singleShot(0, self._fit_columns)
        else:
            self._fit_columns()

    def _set_status(self, dc_count: int, xq_count: int, matched: int):
        core = _code_core(self.code)
        head = f"归一化代码：{core}　DC 行数：{dc_count}　XQ 行数：{xq_count}　匹配：{matched}"
        if matched == 0:
            if xq_count == 0:
                reason = "XQ 表中没有该代码"
            elif dc_count == 0:
                reason = "DC 表中没有该代码"
            else:
                reason = "两边都有数据，但交易日对不上"
            self.status.setText(f"{head}　→ {reason}")
        else:
            self.status.setText(f"{head}　（按交易日配对成功）")

    def showEvent(self, event):
        super().showEvent(event)
        if not self._fitted and self.model.rowCount() > 0:
            self._fitted = True
            QTimer.singleShot(0, self._fit_columns)

    def _fit_columns(self):
        fit_columns(self.view, min_col=100, max_col=240)


# ------------------------- 评论对话框 -------------------------
class CommentDialog(QDialog):
    def __init__(self, title: str, code: str, name: str, text: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{title} · {code} {name}")
        self.resize(560, 320)

        self.edit = QTextEdit(self)
        self.edit.setPlaceholderText("输入对该股票的评论…")
        self.edit.setPlainText(text)
        self.edit.moveCursor(self.edit.textCursor().MoveOperation.End)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.edit)
        layout.addWidget(buttons)

    def text(self) -> str:
        return self.edit.toPlainText().strip()


# ------------------------- 关注名单面板 -------------------------
class FocusStockPanel(QObject):
    FOCUS_SQL = """
        SELECT rowid AS "_rowid",
               "FocusDate" AS "关注日期",
               "StockCode" AS "股票代码",
               "StockName" AS "名称",
               CASE "FocusType" WHEN 1 THEN '重点关注' ELSE '普通关注' END AS "关注类型",
               "FocusType" AS "_focus_type"
        FROM "FocusStock"
        ORDER BY "FocusType" DESC, "FocusDate" DESC, "StockCode";
    """

    COMMENT_SQL = """
        SELECT rowid AS "_rowid",
               "CommentDate" AS "评论日期",
               "StockCode"   AS "股票代码",
               "StockName"   AS "名称",
               "Comment"     AS "评论"
        FROM "FocusStockComment"
        WHERE {code_norm} = {code}
        ORDER BY "CommentDate" DESC;
    """

    EMPTY_COMMENT_SQL = """
        SELECT rowid AS "_rowid",
               "CommentDate" AS "评论日期",
               "StockCode"   AS "股票代码",
               "StockName"   AS "名称",
               "Comment"     AS "评论"
        FROM "FocusStockComment"
        WHERE 1 = 0;
    """

    def __init__(self, view_focus: QTableView, view_comment: QTableView,
                 db: QSqlDatabase, owner: "Widget"):
        super().__init__(view_focus)
        self.db = db
        self.owner = owner
        self.view_focus = view_focus
        self.view_comment = view_comment

        self.model_focus = QSqlQueryModel(self)
        self.model_comment = QSqlQueryModel(self)
        self._col_code = 2
        self._col_name = 3
        self._col_type = 5

        for view in (view_focus, view_comment):
            apply_table_style(view, colorize=False)
            view.installEventFilter(self)

        self.view_focus.setItemDelegate(
            FocusTypeDelegate(self.view_focus, self._focus_type_of))
        self.view_comment.setWordWrap(True)

        view_focus.setModel(self.model_focus)
        view_comment.setModel(self.model_comment)

        view_focus.selectionModel().currentRowChanged.connect(self._on_current_changed)
        view_focus.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        view_focus.customContextMenuRequested.connect(self._show_context_menu)

        view_comment.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        view_comment.customContextMenuRequested.connect(self._show_comment_menu)

        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(60)
        self._fit_timer.timeout.connect(self._refit)

        self.refresh()

    def _refit(self):
        fit_view_to_width(self.view_focus, min_col=90, max_col=260)
        fit_view_to_width(self.view_comment, min_col=90, max_col=360)
        if self.view_comment.wordWrap():
            self.view_comment.resizeRowsToContents()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize and obj in (self.view_focus, self.view_comment):
            self._fit_timer.start()
        return super().eventFilter(obj, event)

    def refresh(self):
        self.model_focus.setQuery(self.FOCUS_SQL, self.db)
        err = self.model_focus.lastError()
        if err.isValid():
            QMessageBox.warning(self.view_focus, "关注名单查询失败", err.text())
            return

        while self.model_focus.canFetchMore():
            self.model_focus.fetchMore()

        self._col_code = self._column_index(self.model_focus, CODE_COL_TITLE)
        self._col_name = self._column_index(self.model_focus, NAME_COL_TITLE)
        self._col_type = self._column_index(self.model_focus, "_focus_type")

        self.view_focus.setColumnHidden(0, True)
        self.view_focus.setColumnHidden(self._col_type, True)

        self._refit()

        if self.model_focus.rowCount() > 0:
            self.view_focus.selectRow(0)
        else:
            self._clear_comments()

    def reload_comments(self):
        index = self.view_focus.currentIndex()
        if index.isValid():
            self._on_current_changed(index, None)
        else:
            self._clear_comments()

    def _load_comments(self, code: str):
        sql = self.COMMENT_SQL.format(
            code=_sql_quote(_code_core(code)),
            code_norm=_norm('"StockCode"'),
        )
        self.model_comment.setQuery(sql, self.db)
        err = self.model_comment.lastError()
        if err.isValid():
            QMessageBox.warning(self.view_comment, "评论查询失败", err.text())
            return

        while self.model_comment.canFetchMore():
            self.model_comment.fetchMore()

        self.view_comment.setColumnHidden(0, True)
        self._refit()

    def _clear_comments(self):
        self.model_comment.setQuery(self.EMPTY_COMMENT_SQL, self.db)
        self.view_comment.setColumnHidden(0, True)
        self._refit()

    def _on_current_changed(self, current, previous):
        if not current.isValid():
            self._clear_comments()
            return
        model = current.model()
        code = model.index(current.row(), self._col_code).data()
        self._load_comments("" if code is None else str(code))

    def _focus_type_of(self, index) -> int:
        if self._col_type < 0:
            return 0
        model = index.model()
        value = model.index(index.row(), self._col_type).data()
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def current_code_name(self):
        index = self.view_focus.currentIndex()
        if not index.isValid():
            return "", ""
        model = index.model()
        row = index.row()
        code = model.index(row, self._col_code).data()
        name = ""
        if self._col_name >= 0:
            name = model.index(row, self._col_name).data() or ""
        return ("" if code is None else str(code)), ("" if name is None else str(name))

    def _show_context_menu(self, pos):
        index = self.view_focus.indexAt(pos)
        if not index.isValid():
            return

        self.view_focus.selectRow(index.row())
        code, name = self.current_code_name()
        if not code:
            return

        row = index.row()
        rowid = self.model_focus.index(row, 0).data()
        ftype = self._focus_type_of(index)

        menu = QMenu(self.view_focus)
        act_comment = menu.addAction("Add comment...")
        act_comment.setData("comment")

        act_flow = menu.addAction("显示资金流向")
        act_flow.setData("flow")

        act_toggle = menu.addAction("普通关注" if ftype == 1 else "重点关注")
        act_toggle.setData("toggle")

        menu.addSeparator()

        act_remove = menu.addAction("Remove Focus")
        act_remove.setData("remove")

        chosen = menu.exec(self.view_focus.viewport().mapToGlobal(pos))
        if chosen is None:
            return

        action = chosen.data()
        if action == "comment":
            self.owner.add_comment(code, name)
        elif action == "flow":
            self.owner.show_stock_flow(code, name)
        elif action == "toggle":
            if rowid is not None:
                self.owner.set_focus_type(int(rowid), 0 if ftype == 1 else 1)
        elif action == "remove":
            self.owner.remove_focus(int(rowid) if rowid is not None else None,
                                    code, name)

    def _show_comment_menu(self, pos):
        index = self.view_comment.indexAt(pos)
        if not index.isValid():
            return

        model = self.model_comment
        row = index.row()

        rowid = model.index(row, 0).data()
        comment = model.index(row, 4).data() or ""
        code = model.index(row, 2).data() or ""
        name = model.index(row, 3).data() or ""

        if rowid is None:
            return

        self.view_comment.selectRow(row)

        menu = QMenu(self.view_comment)
        act_modify = menu.addAction("Modify Comment")
        act_modify.setData("modify")

        chosen = menu.exec(self.view_comment.viewport().mapToGlobal(pos))
        if chosen is not None and chosen.data() == "modify":
            self.owner.modify_comment(int(rowid), str(comment),
                                      str(code), str(name))

    @staticmethod
    def _column_index(model, title: str) -> int:
        for col in range(model.columnCount()):
            if str(model.headerData(col, Qt.Orientation.Horizontal) or "") == title:
                return col
        return -1


# ------------------------- 单个页签的表格控制器 -------------------------
class FundFlowTable(QObject):
    COL_PADDING = 28
    COL_MIN = 72
    COL_MAX = 260
    COL_ROW_NO_MIN = 56
    SAMPLE_ROWS = 50

    def __init__(self, view: QTableView, table: str, db: QSqlDatabase,
                 owner: "Widget", focused_codes: set[str]):
        super().__init__(view)
        if table not in ALLOWED_TABLES:
            raise ValueError(f"不允许的表名：{table}")

        self.view = view
        self.table = table
        self.db = db
        self.owner = owner
        self.focused_codes = focused_codes

        self.model = FundFlowQueryModel(self)
        self.sql = FUND_FLOW_SQL_TEMPLATE.format(table=table)
        self._col_code = -1
        self._col_name = -1

        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(60)
        self._fit_timer.timeout.connect(self.fit_columns)

        view.setModel(self.model)
        apply_table_style(view, focused_codes=focused_codes)
        view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        view.customContextMenuRequested.connect(self._show_context_menu)
        view.doubleClicked.connect(self._open_detail)
        view.installEventFilter(self)

        self.load()

    def load(self) -> bool:
        ok = False
        err = ""
        for _ in range(3):
            ok = self.model.refresh(self.sql, self.db)
            if ok:
                break
            err = self.model.error_text
            if not _is_locked_error(err):
                break
            time.sleep(0.5)

        if not ok:
            QMessageBox.warning(
                self.view, "SQL 执行失败",
                f"表：{self.table}\n\n{err}\n\n"
                "若提示 database is locked，通常是抓取程序正在写库，或数据库位于网络盘上。",
            )
            return False

        self.model.fetch_all()
        self._col_code = self._find_column(CODE_COL_TITLE)
        self._col_name = self._find_column(NAME_COL_TITLE)

        QTimer.singleShot(0, self.fit_columns)
        return True

    def _find_column(self, title: str) -> int:
        for col in range(self.model.columnCount()):
            if str(self.model.headerData(col, Qt.Orientation.Horizontal) or "") == title:
                return col
        return -1

    def row_code_name(self, row: int):
        if self._col_code < 0 or row < 0:
            return "", ""
        code = self.model.index(row, self._col_code).data()
        name = ""
        if self._col_name >= 0:
            name = self.model.index(row, self._col_name).data() or ""
        return ("" if code is None else str(code)), ("" if name is None else str(name))

    def _show_context_menu(self, pos):
        index = self.view.indexAt(pos)
        if not index.isValid():
            return

        code, name = self.row_code_name(index.row())
        if not code:
            return

        self.view.selectRow(index.row())

        menu = QMenu(self.view)
        act_detail = menu.addAction(f"查看 {code} 最近 {DETAIL_DAYS} 个交易日")
        act_detail.setData("detail")

        act_copy = menu.addAction("复制股票代码")
        act_copy.setData("copy")

        menu.addSeparator()

        already = self.owner.is_focused(code)
        act_focus = menu.addAction("已在今日关注名单中" if already else "Add Focus")
        act_focus.setData("focus")
        act_focus.setEnabled(not already)

        chosen = menu.exec(self.view.viewport().mapToGlobal(pos))
        if chosen is None:
            return

        action = chosen.data()
        if action == "detail":
            self.owner.show_stock_detail(code, name, self.table)
        elif action == "copy":
            QApplication.clipboard().setText(code)
        elif action == "focus":
            self.owner.add_focus(code, name)

    def _open_detail(self, index):
        if not index.isValid():
            return
        code, name = self.row_code_name(index.row())
        if code:
            self.owner.show_stock_detail(code, name, self.table)

    def eventFilter(self, obj, event):
        if obj is self.view and event.type() == QEvent.Type.Resize:
            self._fit_timer.start()
        return super().eventFilter(obj, event)

    def _measure_widths(self) -> list[int]:
        model = self.view.model()
        if model is None or model.columnCount() == 0:
            return []

        body_fm = self.view.fontMetrics()
        head_fm = self.view.horizontalHeader().fontMetrics()
        rows = min(max(model.rowCount(), 0), self.SAMPLE_ROWS)

        widths = []
        for col in range(model.columnCount()):
            title = str(model.headerData(
                col, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) or "")
            min_w = self.COL_ROW_NO_MIN if title == ROW_NO_TITLE else self.COL_MIN

            w = head_fm.horizontalAdvance(title) + self.COL_PADDING
            for row in range(rows):
                txt = model.index(row, col).data(Qt.ItemDataRole.DisplayRole)
                if txt is None or txt == "":
                    continue
                w = max(w, body_fm.horizontalAdvance(str(txt)) + 20)

            widths.append(int(max(min_w, min(w, self.COL_MAX))))
        return widths

    def fit_columns(self):
        widths = self._measure_widths()
        if not widths:
            return

        avail = self.view.viewport().width()
        if avail <= 0:
            return

        n = len(widths)
        avail = max(avail, n * self.COL_MIN)
        total = sum(widths)

        if total < avail:
            extra = avail - total
            widths = [w + int(extra * w / total) for w in widths]
            widths[-1] += avail - sum(widths)
        elif total > avail:
            scale = avail / total
            widths = [max(self.COL_MIN, int(w * scale)) for w in widths]
            overflow = sum(widths) - avail
            for i in sorted(range(n), key=lambda k: widths[k], reverse=True):
                if overflow <= 0:
                    break
                cut = min(overflow, widths[i] - self.COL_MIN)
                widths[i] -= cut
                overflow -= cut

        for col, w in enumerate(widths):
            self.view.setColumnWidth(col, w)


# ------------------------- 主窗口 -------------------------
class Widget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_m_MainUI()
        self.ui.setupUi(self)

        self.db = None
        self.write_db = None
        self.tables: list[FundFlowTable] = []
        self._detail_dialogs = []
        self.chart_ratio: QChartView | None = None
        self.chart_limit: QChartView | None = None
        self.focus_panel: FocusStockPanel | None = None
        self.finders: list[TableFinder] = []
        self.focused_codes: set[str] = set()
        self._flow_cache: dict[str, tuple] = {}

        self._init_db()

        if self.db is not None and self.db.isOpen():
            self._reload_focused_codes()

            self.tables = [
                FundFlowTable(
                    self.ui.m_tableViewIndividualFundFlow_DC,
                    DC_TABLE, self.db, self, self.focused_codes),
                FundFlowTable(
                    self.ui.m_tableViewIndividualFundFlow_XQ,
                    XQ_TABLE, self.db, self, self.focused_codes),
            ]
            self._setup_market_temperature()
            self.refresh_charts()
            self._setup_focus_tab()
            self._setup_finders()

        QShortcut(QKeySequence("F5"), self, activated=self.reload_all)

    # ------------------------- 数据库 -------------------------
    def _init_db(self):
        if not DB_PATH.exists():
            QMessageBox.critical(self, "数据库不存在", f"找不到数据库文件：\n{DB_PATH}")
            return

        self.db = QSqlDatabase.addDatabase("QSQLITE")
        self.db.setDatabaseName(str(DB_PATH))
        self.db.setConnectOptions(READ_OPTIONS)
        if not self.db.open():
            QMessageBox.critical(
                self, "数据库打不开",
                f"{DB_PATH}\n\n{self.db.lastError().text()}",
            )

    def _ensure_write_db(self):
        if self.write_db is not None and self.write_db.isOpen():
            return self.write_db

        if not DB_PATH.exists():
            QMessageBox.critical(self, "数据库不存在", f"找不到数据库文件：\n{DB_PATH}")
            return None

        if QSqlDatabase.contains(WRITE_CONNECTION):
            QSqlDatabase.removeDatabase(WRITE_CONNECTION)

        db = QSqlDatabase.addDatabase("QSQLITE", WRITE_CONNECTION)
        db.setDatabaseName(str(DB_PATH))
        db.setConnectOptions(WRITE_OPTIONS)
        if not db.open():
            QMessageBox.critical(self, "无法打开可写连接", db.lastError().text())
            QSqlDatabase.removeDatabase(WRITE_CONNECTION)
            return None

        self.write_db = db
        return db

    # ------------------------- 已关注集合 -------------------------
    def _reload_focused_codes(self):
        codes: set[str] = set()
        if self.db and self.db.isOpen():
            query = QSqlQuery(self.db)
            query.setForwardOnly(True)
            if query.exec('SELECT DISTINCT "StockCode" FROM "FocusStock"'):
                while query.next():
                    value = query.value(0)
                    if value is not None:
                        codes.add(_code_core(value))
            query.finish()

        self.focused_codes.clear()
        self.focused_codes.update(codes)
        self._repaint_tables()

    def _repaint_tables(self):
        for table in self.tables:
            table.view.viewport().update()

    # ------------------------- Ctrl+F 查找 -------------------------
    def _setup_finders(self):
        for table in self.tables:
            self.finders.append(TableFinder(table.view, self))

        if self.focus_panel is not None:
            self.finders.append(TableFinder(self.focus_panel.view_focus, self))

        shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Find), self)
        shortcut.activated.connect(self._on_find_shortcut)

    def _active_finder(self):
        widget = QApplication.focusWidget()
        while widget is not None:
            for finder in self.finders:
                if widget is finder.view:
                    return finder
            widget = widget.parentWidget()

        for finder in self.finders:
            if finder.view.isVisible():
                return finder
        return None

    def _on_find_shortcut(self):
        finder = self._active_finder()
        if finder is None:
            return
        finder.run(self)

    # ------------------------- 市场温度（图表） -------------------------
    def _setup_market_temperature(self):
        main = self.ui.m_tabWidgetMain

        page = None
        for i in range(main.count()):
            if main.tabText(i).strip().lower() == MARKET_TAB_TITLE.lower():
                page = main.widget(i)
                break

        if page is None:
            page = QWidget()
            page.setObjectName("m_tabMarketTemperature")
            main.addTab(page, MARKET_TAB_TITLE)

        inner = page.findChild(QTabWidget)
        if inner is None:
            inner = QTabWidget(page)
            inner.setObjectName("m_tabWidgetTemperature")
            layout = page.layout()
            if layout is None:
                layout = QVBoxLayout(page)
                layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(inner)

        page_ratio = self._ensure_chart_page(inner, "m_tabRisePercent", "Rise Percent")
        page_limit = self._ensure_chart_page(inner, "m_tabRise2Limit", "Rise2Limit")

        self.chart_ratio = self._ensure_chart_view(page_ratio)
        self.chart_limit = self._ensure_chart_view(page_limit)

    @staticmethod
    def _ensure_chart_page(inner: QTabWidget, name: str, title: str) -> QWidget:
        for i in range(inner.count()):
            if inner.widget(i).objectName() == name:
                return inner.widget(i)

        page = QWidget()
        page.setObjectName(name)
        inner.addTab(page, title)
        return page

    @staticmethod
    def _ensure_chart_view(page: QWidget) -> QChartView:
        view = page.findChild(QChartView)
        if view is not None:
            return view

        view = QChartView(QChart(), page)
        view.setRenderHint(QPainter.RenderHint.Antialiasing)

        layout = page.layout()
        if layout is None:
            layout = QVBoxLayout(page)
            layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(view)
        return view

    def refresh_charts(self):
        if not self.db or not self.db.isOpen() or self.chart_ratio is None:
            return

        try:
            self.chart_ratio.setChart(build_ratio_chart(self.db))
        except Exception as exc:
            self._show_chart_error(self.chart_ratio, f"上涨占比统计失败：{exc}")

        try:
            self.chart_limit.setChart(build_limit_chart(self.db))
        except Exception as exc:
            self._show_chart_error(self.chart_limit, f"涨跌停统计失败：{exc}")

    @staticmethod
    def _show_chart_error(view: QChartView, message: str):
        chart = QChart()
        chart.setTitle(message)
        view.setChart(chart)

    # ------------------------- 关注名单页签 -------------------------
    def _setup_focus_tab(self):
        view_focus = self.findChild(QTableView, "m_tableViewFocusStock")
        view_comment = self.findChild(QTableView, "m_tableViewFocusStockComment")

        if view_focus is None or view_comment is None:
            view_focus, view_comment = self._create_focus_tab()

        self.focus_panel = FocusStockPanel(view_focus, view_comment, self.db, self)

    def _create_focus_tab(self):
        main = self.ui.m_tabWidgetMain

        page = main.findChild(QWidget, "m_tabFocusStock")
        if page is None:
            page = QWidget()
            page.setObjectName("m_tabFocusStock")
            main.addTab(page, FOCUS_TAB_TITLE)

        layout = page.layout()
        if layout is None:
            layout = QVBoxLayout(page)
            layout.setContentsMargins(4, 4, 4, 4)

        splitter = QSplitter(Qt.Orientation.Vertical, page)
        view_focus = QTableView(splitter)
        view_focus.setObjectName("m_tableViewFocusStock")
        view_comment = QTableView(splitter)
        view_comment.setObjectName("m_tableViewFocusStockComment")

        splitter.addWidget(view_focus)
        splitter.addWidget(view_comment)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter)

        return view_focus, view_comment

    def refresh_focus(self):
        if self.focus_panel is not None:
            self.focus_panel.refresh()

    # ------------------------- 关注名单读写 -------------------------
    @staticmethod
    def _today_iso() -> str:
        return QDate.currentDate().toString(Qt.DateFormat.ISODate)

    def is_focused(self, code: str) -> bool:
        return _code_core(code) in self.focused_codes

    def add_focus(self, code: str, name: str) -> bool:
        db = self._ensure_write_db()
        if db is None:
            return False

        today = self._today_iso()
        for attempt in range(3):
            query = QSqlQuery(db)
            query.prepare(INSERT_FOCUS_SQL)
            query.addBindValue(today)
            query.addBindValue(code)
            query.addBindValue(name)

            if query.exec():
                affected = query.numRowsAffected()
                query.finish()
                self._reload_focused_codes()
                if affected == 0:
                    QMessageBox.information(
                        self, "提示", f"{code} {name} 已在 {today} 的关注名单中。")
                    self.refresh_focus()
                    return False
                QMessageBox.information(
                    self, "已添加关注", f"已把 {code} {name} 加入 {today} 的关注名单（普通关注）。")
                self.refresh_focus()
                return True

            err = query.lastError().text()
            query.finish()
            if not _is_locked_error(err) or attempt == 2:
                QMessageBox.critical(self, "添加关注失败", err)
                return False
            time.sleep(0.5)

        return False

    def set_focus_type(self, rowid: int, focus_type: int) -> bool:
        db = self._ensure_write_db()
        if db is None:
            return False

        query = QSqlQuery(db)
        query.prepare(UPDATE_FOCUS_TYPE_SQL)
        query.addBindValue(int(focus_type))
        query.addBindValue(int(rowid))

        if not query.exec():
            err = query.lastError().text()
            query.finish()
            QMessageBox.critical(self, "修改关注类型失败", err)
            return False

        affected = query.numRowsAffected()
        query.finish()

        self.refresh_focus()
        if affected <= 0:
            QMessageBox.warning(self, "修改关注类型失败", "没有找到对应的记录。")
            return False
        return True

    def remove_focus(self, rowid, code: str, name: str) -> bool:
        answer = QMessageBox.question(
            self, "Remove Focus",
            f"确定要移除对 {code} {name} 的关注吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False

        db = self._ensure_write_db()
        if db is None:
            return False

        query = QSqlQuery(db)
        query.prepare(DELETE_FOCUS_SQL)
        query.addBindValue(int(rowid) if rowid is not None else -1)

        if not query.exec():
            err = query.lastError().text()
            query.finish()
            QMessageBox.critical(self, "移除关注失败", err)
            return False

        affected = query.numRowsAffected()
        query.finish()

        self._reload_focused_codes()
        self.refresh_focus()
        self._flow_cache.clear()

        if affected <= 0:
            QMessageBox.information(self, "提示", f"关注名单中没有找到 {code}。")
            return False

        QMessageBox.information(
            self, "已移除关注", f"已从关注名单移除 {code} {name}（{affected} 条记录）。")
        return True

    def add_comment(self, code: str, name: str) -> bool:
        dlg = CommentDialog("Add comment", code, name, "", self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False

        text = dlg.text()
        if not text:
            QMessageBox.information(self, "提示", "评论内容为空，未保存。")
            return False

        db = self._ensure_write_db()
        if db is None:
            return False

        query = QSqlQuery(db)
        query.prepare(INSERT_COMMENT_SQL)
        query.addBindValue(self._today_iso())
        query.addBindValue(code)
        query.addBindValue(name)
        query.addBindValue(text)

        if not query.exec():
            err = query.lastError().text()
            query.finish()
            QMessageBox.critical(self, "保存评论失败", err)
            return False

        query.finish()
        if self.focus_panel is not None:
            self.focus_panel.reload_comments()
        return True

    def modify_comment(self, rowid: int, old_text: str,
                       code: str = "", name: str = "") -> bool:
        dlg = CommentDialog("Modify Comment", code, name, old_text, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False

        text = dlg.text()
        if not text:
            QMessageBox.information(self, "提示", "评论内容不能为空。")
            return False
        if text == old_text:
            return False

        db = self._ensure_write_db()
        if db is None:
            return False

        query = QSqlQuery(db)
        query.prepare(UPDATE_COMMENT_SQL)
        query.addBindValue(text)
        query.addBindValue(rowid)

        if not query.exec():
            err = query.lastError().text()
            query.finish()
            QMessageBox.critical(self, "修改评论失败", err)
            return False

        affected = query.numRowsAffected()
        query.finish()

        if affected <= 0:
            QMessageBox.warning(self, "修改评论失败", "没有找到对应的记录。")
            return False

        if self.focus_panel is not None:
            self.focus_panel.reload_comments()
        return True

    # ------------------------- 明细 / 资金流向窗口 -------------------------
    def show_stock_detail(self, code: str, name: str, table: str):
        dlg = StockDetailDialog(code, name, table, self.db, self)
        dlg.destroyed.connect(lambda _=None, d=dlg: self._forget_dialog(d))
        self._detail_dialogs.append(dlg)
        dlg.show()

    def show_stock_flow(self, code: str, name: str):
        dlg = StockFlowDialog(code, name, self.db, self, self._flow_cache)
        dlg.destroyed.connect(lambda _=None, d=dlg: self._forget_dialog(d))
        self._detail_dialogs.append(dlg)
        dlg.show()
        dlg.start()

    def _forget_dialog(self, dlg):
        if dlg in self._detail_dialogs:
            self._detail_dialogs.remove(dlg)

    # ------------------------- 刷新 -------------------------
    def reload_all(self):
        self._flow_cache.clear()
        self._reload_focused_codes()
        for table in self.tables:
            table.load()
        self.refresh_charts()
        self.refresh_focus()
        for finder in self.finders:
            finder.refresh()

    # ------------------------- 收尾 -------------------------
    def closeEvent(self, event):
        if self.write_db is not None:
            self.write_db.close()
            self.write_db = None
        if QSqlDatabase.contains(WRITE_CONNECTION):
            QSqlDatabase.removeDatabase(WRITE_CONNECTION)
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = Widget()
    w.show()
    sys.exit(app.exec())