# -*- coding: utf-8 -*-
"""StockTip 主窗口：展示 IndividualFundFlow_DC 的“涨停后背离”筛选结果。"""

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QEvent, QTimer
from PySide6.QtGui import QBrush, QColor, QPalette, QShortcut, QKeySequence
from PySide6.QtSql import QSqlDatabase, QSqlQueryModel
from PySide6.QtWidgets import (
    QApplication, QWidget, QMessageBox, QHeaderView, QAbstractItemView,
    QStyledItemDelegate, QStyle,
)

from ui_form import Ui_m_MainUI

# ----------------------------- 配置 -----------------------------
DB_PATH = Path(r"U:\Grab\Tip.db")      # 改成 Tip.db 的真实路径

MONEY_COL = "主力净流入"
RISE_COL = "涨跌幅"
ROW_NO_TITLE = "行号"

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


# ------------------------- 颜色规则 -------------------------
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


class ThresholdColorDelegate(QStyledItemDelegate):
    """按列头名称识别列，按数值给单元格上色，并统一居中。"""

    RULES = {
        MONEY_COL: money_flow_color,
        RISE_COL: rise_color,
    }

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)

        # 所有单元格统一居中
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
        # 选中行保留系统高亮色，避免看不出当前选中行
        if not (option.state & QStyle.StateFlag.State_Selected):
            option.backgroundBrush = QBrush(QColor(bg))
            option.palette.setColor(QPalette.ColorRole.Text, QColor(fg))


class FundFlowQueryModel(QSqlQueryModel):
    """QSqlQueryModel 的错误默认会被吞掉，这里把它保存下来方便提示。"""

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


class Widget(QWidget):
    # ---- 列宽策略，想调“松紧”改这几个数 ----
    COL_PADDING = 28      # 表头文字左右留白
    COL_MIN = 72          # 普通列最小宽度
    COL_MAX = 260         # 单列最大宽度
    COL_ROW_NO_MIN = 56   # “行号”列最小宽度
    SAMPLE_ROWS = 50      # 取样多少行来估算内容宽度

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_m_MainUI()
        self.ui.setupUi(self)

        self.db = None
        self.model = FundFlowQueryModel(self)

        # 防抖：窗口连续缩放时只在停下来后重算一次列宽
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
        # 只读打开：避免误写，也避免路径写错时悄悄建一个空库
        self.db.setConnectOptions("QSQLITE_OPEN_READONLY")
        if not self.db.open():
            QMessageBox.critical(
                self, "数据库打不开",
                f"{DB_PATH}\n\n{self.db.lastError().text()}",
            )

    # ------------------------- 表格外观 -------------------------
    def _init_table_view(self):
        view = self.ui.m_tableViewIndividualFundFlow_DC
        view.setModel(self.model)                      # 直接挂查询模型（无代理层）
        view.setItemDelegate(ThresholdColorDelegate(view))

        view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        view.setAlternatingRowColors(True)
        view.setWordWrap(False)
        view.setShowGrid(False)                        # 去掉网格线，靠斑马纹分隔
        view.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        view.verticalHeader().setVisible(False)
        view.verticalHeader().setDefaultSectionSize(30)

        header = view.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)   # 表头居中
        header.setHighlightSections(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)                        # 由自适应算法铺满
        header.setMinimumHeight(34)
        font = header.font()
        font.setBold(True)
        header.setFont(font)

        view.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.ui.m_tableViewIndividualFundFlow_DC and event.type() == QEvent.Type.Resize:
            self._width_timer.start()
        return super().eventFilter(obj, event)

    # ------------------------- 列宽计算 -------------------------
    def _measure_widths(self, view) -> list[int]:
        """按表头文字 + 样例行内容估算每列自然宽度。"""
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
        """把各列宽度按比例缩放，正好铺满表格可视区。"""
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
            # 内容偏窄：按比例把富余空间摊给各列
            extra = avail - total
            widths = [w + int(extra * w / total) for w in widths]
            widths[-1] += avail - sum(widths)        # 余数补到最后一列
        elif total > avail:
            # 内容偏宽：等比压缩，压到最小宽度就停，剩下的从最宽的列扣
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

        # 等布局完成后再算列宽
        QTimer.singleShot(0, self._fit_columns)
        self.ui.m_tabWidgetMain.setCurrentIndex(0)
        return True


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = Widget()
    w.show()
    sys.exit(app.exec())