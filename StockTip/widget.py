# -*- coding: utf-8 -*-
"""StockTip 主窗口：两个页签分别展示 DC / XQ 两张表的“涨停后背离”结果。"""

import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QObject, QDate, QEvent, QTimer
from PySide6.QtGui import QBrush, QColor, QPalette, QShortcut, QKeySequence
from PySide6.QtSql import QSqlDatabase, QSqlQuery, QSqlQueryModel
from PySide6.QtWidgets import (
    QApplication, QWidget, QDialog, QMenu, QMessageBox, QHeaderView,
    QAbstractItemView, QTableView, QVBoxLayout, QStyledItemDelegate, QStyle,
)

from ui_form import Ui_m_MainUI

# ----------------------------- 配置 -----------------------------
DB_PATH = Path(r"U:\Grab\Tip.db")
WRITE_CONNECTION = "stocktip_write"

READ_OPTIONS = "QSQLITE_OPEN_READONLY;QSQLITE_BUSY_TIMEOUT=15000"
WRITE_OPTIONS = "QSQLITE_BUSY_TIMEOUT=15000"

MONEY_COL = "主力净流入"
RISE_COL = "涨跌幅"
ROW_NO_TITLE = "行号"
DETAIL_DAYS = 30

# 允许查询的表（白名单，防止表名被拼接成任意 SQL）
ALLOWED_TABLES = ("IndividualFundFlow_DC", "IndividualFundFlow_XQ")

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

DETAIL_SQL = {
    "IndividualFundFlow_DC": """
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
    """,
    "IndividualFundFlow_XQ": """
        SELECT
            "TradeDate"          AS "交易日",
            "StockCode"          AS "股票代码",
            "StockName"          AS "名称",
            "Price"              AS "收盘价",
            "Rise"               AS "涨跌幅(%)",
            "FundFlow_MainForce" AS "主力净流入(万元)"
        FROM "IndividualFundFlow_XQ"
        WHERE "StockCode" = {code}
        ORDER BY "TradeDate" DESC
        LIMIT {limit};
    """,
}

INSERT_FOCUS_SQL = """
INSERT OR IGNORE INTO "FocusStock" ("FocusDate", "StockCode", "StockName")
VALUES (?, ?, ?);
"""


# ------------------------- 工具 -------------------------
def _sql_quote(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _is_locked_error(text: str) -> bool:
    t = (text or "").lower()
    return "locked" in t or "busy" in t


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

    def fetch_all(self):
        """结果集一次取完，语句走到 SQLITE_DONE，读事务立即释放。"""
        guard = 0
        while self.canFetchMore() and guard < 20000:
            self.fetchMore()
            guard += 1


def apply_table_style(view: QTableView, colorize: bool = True):
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


# ------------------------- 明细窗口 -------------------------
class StockDetailDialog(QDialog):
    """某只股票最近 N 个交易日的明细（按来源表选列）。"""

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
            code=_sql_quote(code), limit=int(DETAIL_DAYS))
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


# ------------------------- 单个页签的表格控制器 -------------------------
class FundFlowTable(QObject):
    """把一个 QTableView 和它背后的查询、右键菜单、列宽策略绑在一起。"""

    COL_PADDING = 28
    COL_MIN = 72
    COL_MAX = 260
    COL_ROW_NO_MIN = 56
    SAMPLE_ROWS = 50

    def __init__(self, view: QTableView, table: str, db: QSqlDatabase, owner: "Widget"):
        super().__init__(view)
        if table not in ALLOWED_TABLES:
            raise ValueError(f"不允许的表名：{table}")

        self.view = view
        self.table = table
        self.db = db
        self.owner = owner

        self.model = FundFlowQueryModel(self)
        self.sql = FUND_FLOW_SQL_TEMPLATE.format(table=table)
        self._col_code = -1
        self._col_name = -1

        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(60)
        self._fit_timer.timeout.connect(self.fit_columns)

        view.setModel(self.model)
        apply_table_style(view)
        view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        view.customContextMenuRequested.connect(self._show_context_menu)
        view.doubleClicked.connect(self._open_detail)
        view.installEventFilter(self)

        self.load()

    # ---------- 加载 ----------
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
        self._col_code = self._find_column("股票代码")
        self._col_name = self._find_column("名称")

        QTimer.singleShot(0, self.fit_columns)
        return True

    # ---------- 行信息 ----------
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

    # ---------- 右键菜单 ----------
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

    # ---------- 事件 / 列宽 ----------
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

        self.db = None            # 只读连接（两个页签共用）
        self.write_db = None      # 可写连接（Add Focus）
        self.tables: list[FundFlowTable] = []
        self._detail_dialogs = []

        self._init_db()

        if self.db is not None and self.db.isOpen():
            self.tables = [
                FundFlowTable(
                    self.ui.m_tableViewIndividualFundFlow_DC,
                    "IndividualFundFlow_DC", self.db, self),
                FundFlowTable(
                    self.ui.m_tableViewIndividualFundFlow_XQ,
                    "IndividualFundFlow_XQ", self.db, self),
            ]

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

    # ------------------------- 关注名单 -------------------------
    @staticmethod
    def _today_iso() -> str:
        return QDate.currentDate().toString(Qt.DateFormat.ISODate)

    def is_focused(self, code: str) -> bool:
        if not self.db or not self.db.isOpen():
            return False

        query = QSqlQuery(self.db)
        query.setForwardOnly(True)
        query.prepare(
            'SELECT 1 FROM "FocusStock" WHERE "StockCode" = ? AND "FocusDate" = ?')
        query.addBindValue(code)
        query.addBindValue(self._today_iso())

        found = False
        if query.exec() and query.next():
            found = True
        query.finish()
        return found

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
                if affected == 0:
                    QMessageBox.information(
                        self, "提示", f"{code} {name} 已在 {today} 的关注名单中。")
                    return False
                QMessageBox.information(
                    self, "已添加关注", f"已把 {code} {name} 加入 {today} 的关注名单。")
                return True

            err = query.lastError().text()
            query.finish()
            if not _is_locked_error(err) or attempt == 2:
                QMessageBox.critical(self, "添加关注失败", err)
                return False
            time.sleep(0.5)

        return False

    # ------------------------- 明细窗口 -------------------------
    def show_stock_detail(self, code: str, name: str, table: str):
        dlg = StockDetailDialog(code, name, table, self.db, self)
        dlg.destroyed.connect(lambda _=None, d=dlg: self._forget_dialog(d))
        self._detail_dialogs.append(dlg)
        dlg.show()

    def _forget_dialog(self, dlg):
        if dlg in self._detail_dialogs:
            self._detail_dialogs.remove(dlg)

    # ------------------------- 刷新 -------------------------
    def reload_all(self):
        for table in self.tables:
            table.load()

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