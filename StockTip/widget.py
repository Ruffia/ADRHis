# -*- coding: utf-8 -*-
"""StockTip 主窗口：展示 IndividualFundFlow_DC 的“涨停后背离”筛选结果。"""

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QEvent, QTimer
from PySide6.QtGui import QBrush, QColor, QPalette, QShortcut, QKeySequence
from PySide6.QtSql import QSqlDatabase, QSqlQueryModel
from PySide6.QtWidgets import (
    QApplication, QWidget, QDialog, QMenu, QMessageBox, QHeaderView,
    QAbstractItemView, QTableView, QVBoxLayout, QStyledItemDelegate, QStyle,
)

from ui_form import Ui_m_MainUI

# ----------------------------- 配置 -----------------------------
DB_PATH = Path(r"U:\Grab\Tip.db")      # 改成 Tip.db 的真实路径

MONEY_COL = "主力净流入"
RISE_COL = "涨跌幅"
ROW_NO_TITLE = "行号"
DETAIL_DAYS = 30          # 明细窗口显示最近多少个交易日

SQL_FUND_FLOW = r"""
WITH cal AS (
    SELECT "TradeDate", ROW_NUMBER() OVER (ORDER BY "TradeDate") AS dno
    FROM (SELECT DISTINCT "TradeDate" FROM "IndividualFundFlow_DC")
),
seqd AS (
    SELECT
        f."TradeDate", f."StockCode", f."StockName", f."Price", f."Rise",
        f."FundFlow_MainForce",
        c.dno AS mkt_dno,
        ROW_NUMBER() OVER (PARTITION BY f."StockCode" ORDER BY f."TradeDate") AS seq
    FROM "IndividualFundFlow_DC" f
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
    WHERE lu_seq IS NOT NULL              -- 有过涨停
      AND seq > lu_seq                    -- 涨停之后
      AND seq - lu_seq <= 10              -- 涨停后 10 个（个股）交易日内
      AND "Rise" < 0                      -- 下跌
      AND "FundFlow_MainForce" > 0        -- 主力净流入
      AND lu_mkt_dno >= (SELECT MAX(dno) FROM cal) - 10   -- 涨停在最近 10 个交易日内
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

# 明细窗口：表里全部 10 列
DETAIL_SQL_TEMPLATE = """
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
WHERE "StockCode" = {code}
ORDER BY "TradeDate" DESC
LIMIT {limit};
"""


# ------------------------- 工具 -------------------------
def _sql_quote(value) -> str:
    """把值安全地拼进 SQL 字符串（单引号转义）。"""
    return "'" + str(value).replace("'", "''") + "'"


def money_flow_color(v: float):
    """主力净流入：> 2000 深红，> 1000 中红，> 500 浅红。"""
    if v > 2000:
        return "#C62828", "#FFFFFF"
    if v > 1000:
        return "#E57373", "#FFFFFF"
    if v > 500:
        return "#FFCDD2", "#8B0000"
    return None


def rise_color(v: float):
    """涨跌幅：< -8 深绿，< -5 中绿，< -3 浅绿。"""
    if v < -8:
        return "#2E7D32", "#FFFFFF"
    if v < -5:
        return "#81C784", "#1B5E20"
    if v < -3:
        return "#C8E6C9", "#1B5E20"
    return None


def fit_columns(view: QTableView, min_col: int = 80, max_col: int = 220,
                padding: int = 24, sample_rows: int = 50):
    """按表头 + 内容估算列宽，并在总宽不足时按比例铺满。"""
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


class ThresholdColorDelegate(QStyledItemDelegate):
    """按列头名称识别列，按数值给单元格上色，并统一居中。"""

    RULES = {
        MONEY_COL: money_flow_color,
        RISE_COL: rise_color,
    }

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)

        option.displayAlignment = Qt.AlignmentFlag.AlignCenter

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
        if not (option.state & QStyle.StateFlag.State_Selected):
            option.backgroundBrush = QBrush(QColor(bg))
            option.palette.setColor(QPalette.ColorRole.Text, QColor(fg))


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


def apply_table_style(view: QTableView, colorize: bool = True):
    """主表和明细表共用的外观设置。"""
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
        view.setItemDelegate(ThresholdColorDelegate(view))


# ------------------------- 个股明细窗口（全部列） -------------------------
class StockDetailDialog(QDialog):
    """某只股票最近 N 个交易日的全部字段。"""

    def __init__(self, code: str, name: str, db: QSqlDatabase, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(f"{code} {name} · 最近 {DETAIL_DAYS} 个交易日")
        self.resize(1240, 560)          # 10 列，窗口给宽一点
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
        sql = DETAIL_SQL_TEMPLATE.format(code=_sql_quote(code), limit=int(DETAIL_DAYS))
        self.model.setQuery(sql, db)
        err = self.model.lastError()
        if err.isValid():
            QMessageBox.warning(self, "明细查询失败", err.text())

    def showEvent(self, event):
        super().showEvent(event)
        if not self._fitted:
            self._fitted = True
            QTimer.singleShot(0, self._fit_columns)

    def _fit_columns(self):
        fit_columns(self.view, min_col=88, max_col=200)


# ------------------------- 主窗口 -------------------------
class Widget(QWidget):
    COL_PADDING = 28
    COL_MIN = 72
    COL_MAX = 260
    COL_ROW_NO_MIN = 56
    SAMPLE_ROWS = 50

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_m_MainUI()
        self.ui.setupUi(self)

        self.db = None
        self.model = FundFlowQueryModel(self)
        self._col_code = -1
        self._col_name = -1
        self._detail_dialogs = []          # 防止明细窗口被 GC 掉

        self._width_timer = QTimer(self)
        self._width_timer.setSingleShot(True)
        self._width_timer.setInterval(60)
        self._width_timer.timeout.connect(self._fit_columns)

        self._init_db()
        self._init_table_view()
        self.load_fund_flow()

        QShortcut(QKeySequence("F5"), self, activated=self.load_fund_flow)

    # ------------------------- 数据库 -------------------------
    def _init_db(self):
        self.db = QSqlDatabase.addDatabase("QSQLITE")
        self.db.setDatabaseName(str(DB_PATH))
        self.db.setConnectOptions("QSQLITE_OPEN_READONLY")
        if not self.db.open():
            QMessageBox.critical(
                self, "数据库打不开",
                f"{DB_PATH}\n\n{self.db.lastError().text()}",
            )

    # ------------------------- 表格 -------------------------
    def _init_table_view(self):
        view = self.ui.m_tableViewIndividualFundFlow_DC
        view.setModel(self.model)
        apply_table_style(view)

        view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        view.customContextMenuRequested.connect(self._show_context_menu)
        view.doubleClicked.connect(self._open_detail_from_index)

        view.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.ui.m_tableViewIndividualFundFlow_DC and event.type() == QEvent.Type.Resize:
            self._width_timer.start()
        return super().eventFilter(obj, event)

    # ------------------------- 右键菜单 -------------------------
    def _find_column(self, title: str) -> int:
        for col in range(self.model.columnCount()):
            if str(self.model.headerData(col, Qt.Orientation.Horizontal) or "") == title:
                return col
        return -1

    def _row_code_name(self, row: int):
        if self._col_code < 0 or row < 0:
            return "", ""
        code = self.model.index(row, self._col_code).data()
        name = ""
        if self._col_name >= 0:
            name = self.model.index(row, self._col_name).data() or ""
        return ("" if code is None else str(code)), ("" if name is None else str(name))

    def _show_context_menu(self, pos):
        view = self.ui.m_tableViewIndividualFundFlow_DC
        index = view.indexAt(pos)
        if not index.isValid():
            return

        code, name = self._row_code_name(index.row())
        if not code:
            return

        view.selectRow(index.row())

        menu = QMenu(self)
        act_detail = menu.addAction(f"查看 {code} 最近 {DETAIL_DAYS} 个交易日")
        act_detail.setData("detail")
        act_copy = menu.addAction("复制股票代码")
        act_copy.setData("copy")

        chosen = menu.exec(view.viewport().mapToGlobal(pos))
        if chosen is None:
            return

        action = chosen.data()
        if action == "detail":
            self.show_stock_detail(code, name)
        elif action == "copy":
            QApplication.clipboard().setText(code)

    def _open_detail_from_index(self, index):
        if not index.isValid():
            return
        code, name = self._row_code_name(index.row())
        if code:
            self.show_stock_detail(code, name)

    def show_stock_detail(self, code: str, name: str):
        dlg = StockDetailDialog(code, name, self.db, self)
        dlg.destroyed.connect(lambda _=None, d=dlg: self._forget_dialog(d))
        self._detail_dialogs.append(dlg)
        dlg.show()

    def _forget_dialog(self, dlg):
        if dlg in self._detail_dialogs:
            self._detail_dialogs.remove(dlg)

    # ------------------------- 列宽 -------------------------
    def _measure_widths(self, view) -> list[int]:
        model = view.model()
        if model is None or model.columnCount() == 0:
            return []

        body_fm = view.fontMetrics()
        head_fm = view.horizontalHeader().fontMetrics()
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

    def _fit_columns(self):
        view = self.ui.m_tableViewIndividualFundFlow_DC
        widths = self._measure_widths(view)
        if not widths:
            return

        avail = view.viewport().width()
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
            view.setColumnWidth(col, w)

    # ------------------------- 查询 -------------------------
    def load_fund_flow(self) -> bool:
        if not self.db or not self.db.isOpen():
            return False
        if not self.model.refresh(SQL_FUND_FLOW, self.db):
            QMessageBox.critical(self, "SQL 执行失败", self.model.error_text)
            return False

        self._col_code = self._find_column("股票代码")
        self._col_name = self._find_column("名称")

        QTimer.singleShot(0, self._fit_columns)
        self.ui.m_tabWidgetMain.setCurrentIndex(0)
        return True


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = Widget()
    w.show()
    sys.exit(app.exec())