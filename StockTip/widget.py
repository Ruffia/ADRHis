# -*- coding: utf-8 -*-
import sys
from pathlib import Path

from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtSql import QSqlDatabase, QSqlQueryModel
from PySide6.QtWidgets import (
    QApplication, QWidget, QMessageBox, QHeaderView, QAbstractItemView,
)

from ui_form import Ui_m_MainUI

# 改成 Tip.db 的真实位置
DB_PATH = Path(r"U:\Grab\Tip.db")

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
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_m_MainUI()
        self.ui.setupUi(self)

        self.db = None
        self.model = FundFlowQueryModel(self)

        self._init_db()
        self._init_table_view()
        self.load_fund_flow()

        # F5 手动刷新
        QShortcut(QKeySequence("F5"), self, activated=self.load_fund_flow)

    # ---------- 数据库 ----------
    def _init_db(self):
        self.db = QSqlDatabase.addDatabase("QSQLITE")
        self.db.setDatabaseName(str(DB_PATH))
        # 只读打开，避免误写、也避免路径写错时悄悄建一个空库
        self.db.setConnectOptions("QSQLITE_OPEN_READONLY")
        if not self.db.open():
            QMessageBox.critical(
                self, "数据库打不开",
                f"{DB_PATH}\n\n{self.db.lastError().text()}",
            )

    # ---------- 表格外观 ----------
    def _init_table_view(self):
        view = self.ui.m_tableViewIndividualFundFlow_DC
        view.setModel(self.model)
        view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        view.setAlternatingRowColors(True)
        view.setWordWrap(False)
        view.verticalHeader().setVisible(False)

        header = view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)

    # ---------- 查询 ----------
    def load_fund_flow(self) -> bool:
        if not self.db or not self.db.isOpen():
            return False
        if not self.model.refresh(SQL_FUND_FLOW, self.db):
            QMessageBox.critical(self, "SQL 执行失败", self.model.error_text)
            return False

        view = self.ui.m_tableViewIndividualFundFlow_DC
        view.resizeColumnsToContents()

        # 默认显示第一个页签（你的 Designer 里设成了 1）
        self.ui.m_tabWidgetMain.setCurrentIndex(0)
        return True


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = Widget()
    w.show()
    sys.exit(app.exec())