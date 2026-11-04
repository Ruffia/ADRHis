# -*- coding: utf-8 -*-
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPalette, QShortcut, QKeySequence
from PySide6.QtSql import QSqlDatabase, QSqlQueryModel
from PySide6.QtWidgets import (
    QApplication, QWidget, QMessageBox, QHeaderView, QAbstractItemView,
    QStyledItemDelegate, QStyle,
)

from ui_form import Ui_m_MainUI

DB_PATH = Path(r"U:\Grab\Tip.db")      # 改成实际路径

MONEY_COL = "主力净流入"
RISE_COL = "涨跌幅"


# ---------- 颜色规则：想调色只改这两个函数 ----------
def money_flow_color(v: float):
    """> 2000 深红，> 1000 中红，> 500 浅红；其余不染色。"""
    if v >= 2000:
        return "#C62828", "#FFFFFF"
    if v >= 1000:
        return "#E57373", "#FFFFFF"
    if v >= 500:
        return "#FFCDD2", "#8B0000"
    return None


def rise_color(v: float):
    """跌幅 < -8 深绿，< -5 中绿，< -3 浅绿；其余不染色。"""
    if v <= -8:
        return "#2E7D32", "#FFFFFF"
    if v <= -5:
        return "#81C784", "#1B5E20"
    if v <= -3:
        return "#C8E6C9", "#1B5E20"
    return None


class ThresholdColorDelegate(QStyledItemDelegate):
    """按列头名称识别列，按数值给单元格上色。"""

    RULES = {
        MONEY_COL: money_flow_color,
        RISE_COL: rise_color,
    }

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)

        model = index.model()
        header = model.headerData(
            index.column(), Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole
        ) or ""
        rule = next((fn for name, fn in self.RULES.items() if header.startswith(name)), None)
        if rule is None:
            return

        # 右对齐更适合数字列
        option.displayAlignment = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        try:
            number = float(index.data(Qt.ItemDataRole.DisplayRole))
        except (TypeError, ValueError):
            return

        colors = rule(number)
        if colors is None:
            return                      # 未达阈值，保持默认外观

        bg, fg = colors
        # 选中行保留系统高亮色，否则用户看不出当前选的是哪一行
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
    WHERE lu_seq IS NOT NULL
      AND seq > lu_seq
      AND seq - lu_seq <= 10
      AND "Rise" < 0
      AND "FundFlow_MainForce" > 0
      AND lu_mkt_dno >= (SELECT MAX(dno) FROM cal) - 10
)
SELECT
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


class Widget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_m_MainUI()
        self.ui.setupUi(self)

        self.db = None
        self.model = FundFlowQueryModel(self)

        self._init_db()
        self._init_table_view()
        self.load_fund_flow()

        QShortcut(QKeySequence("F5"), self, activated=self.load_fund_flow)

    def _init_db(self):
        self.db = QSqlDatabase.addDatabase("QSQLITE")
        self.db.setDatabaseName(str(DB_PATH))
        self.db.setConnectOptions("QSQLITE_OPEN_READONLY")
        if not self.db.open():
            QMessageBox.critical(
                self, "数据库打不开",
                f"{DB_PATH}\n\n{self.db.lastError().text()}",
            )

    def _init_table_view(self):
        view = self.ui.m_tableViewIndividualFundFlow_DC
        view.setModel(self.model)
        view.setItemDelegate(ThresholdColorDelegate(view))   # 上色
        view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        view.setAlternatingRowColors(True)
        view.setWordWrap(False)
        view.verticalHeader().setVisible(False)

        header = view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)

    def load_fund_flow(self) -> bool:
        if not self.db or not self.db.isOpen():
            return False
        if not self.model.refresh(SQL_FUND_FLOW, self.db):
            QMessageBox.critical(self, "SQL 执行失败", self.model.error_text)
            return False

        view = self.ui.m_tableViewIndividualFundFlow_DC
        view.resizeColumnsToContents()
        self.ui.m_tabWidgetMain.setCurrentIndex(0)
        return True


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = Widget()
    w.show()
    sys.exit(app.exec())