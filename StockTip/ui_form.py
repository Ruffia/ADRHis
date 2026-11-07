# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'form.ui'
##
## Created by: Qt User Interface Compiler version 6.12.0
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QHeaderView, QSizePolicy, QTabWidget,
    QTableView, QWidget)

class Ui_m_MainUI(object):
    def setupUi(self, m_MainUI):
        if not m_MainUI.objectName():
            m_MainUI.setObjectName(u"m_MainUI")
        m_MainUI.resize(1117, 701)
        self.m_tabWidgetMain = QTabWidget(m_MainUI)
        self.m_tabWidgetMain.setObjectName(u"m_tabWidgetMain")
        self.m_tabWidgetMain.setGeometry(QRect(10, 10, 1091, 681))
        self.m_tabIndividualFundFlow_DC = QWidget()
        self.m_tabIndividualFundFlow_DC.setObjectName(u"m_tabIndividualFundFlow_DC")
        self.m_tableViewIndividualFundFlow_DC = QTableView(self.m_tabIndividualFundFlow_DC)
        self.m_tableViewIndividualFundFlow_DC.setObjectName(u"m_tableViewIndividualFundFlow_DC")
        self.m_tableViewIndividualFundFlow_DC.setGeometry(QRect(2, 0, 1081, 651))
        self.m_tabWidgetMain.addTab(self.m_tabIndividualFundFlow_DC, "")
        self.m_tabIndividualFundFlow_XQ = QWidget()
        self.m_tabIndividualFundFlow_XQ.setObjectName(u"m_tabIndividualFundFlow_XQ")
        self.m_tableViewIndividualFundFlow_XQ = QTableView(self.m_tabIndividualFundFlow_XQ)
        self.m_tableViewIndividualFundFlow_XQ.setObjectName(u"m_tableViewIndividualFundFlow_XQ")
        self.m_tableViewIndividualFundFlow_XQ.setGeometry(QRect(2, 2, 1081, 641))
        self.m_tabWidgetMain.addTab(self.m_tabIndividualFundFlow_XQ, "")
        self.m_tabFocusStock = QWidget()
        self.m_tabFocusStock.setObjectName(u"m_tabFocusStock")
        self.m_tableViewFocusStock = QTableView(self.m_tabFocusStock)
        self.m_tableViewFocusStock.setObjectName(u"m_tableViewFocusStock")
        self.m_tableViewFocusStock.setGeometry(QRect(0, 1, 271, 651))
        self.m_tableViewFocusStockComment = QTableView(self.m_tabFocusStock)
        self.m_tableViewFocusStockComment.setObjectName(u"m_tableViewFocusStockComment")
        self.m_tableViewFocusStockComment.setGeometry(QRect(280, 1, 801, 651))
        self.m_tabWidgetMain.addTab(self.m_tabFocusStock, "")
        self.m_tabMarketTemperature = QWidget()
        self.m_tabMarketTemperature.setObjectName(u"m_tabMarketTemperature")
        self.m_tabWidgetMarketTeperature = QTabWidget(self.m_tabMarketTemperature)
        self.m_tabWidgetMarketTeperature.setObjectName(u"m_tabWidgetMarketTeperature")
        self.m_tabWidgetMarketTeperature.setGeometry(QRect(0, 0, 1081, 651))
        self.m_tabRisePercent = QWidget()
        self.m_tabRisePercent.setObjectName(u"m_tabRisePercent")
        self.m_tabWidgetMarketTeperature.addTab(self.m_tabRisePercent, "")
        self.m_tabRise2Limit = QWidget()
        self.m_tabRise2Limit.setObjectName(u"m_tabRise2Limit")
        self.m_tabWidgetMarketTeperature.addTab(self.m_tabRise2Limit, "")
        self.m_tabWidgetMain.addTab(self.m_tabMarketTemperature, "")

        self.retranslateUi(m_MainUI)

        self.m_tabWidgetMain.setCurrentIndex(2)
        self.m_tabWidgetMarketTeperature.setCurrentIndex(0)


        QMetaObject.connectSlotsByName(m_MainUI)
    # setupUi

    def retranslateUi(self, m_MainUI):
        m_MainUI.setWindowTitle(QCoreApplication.translate("m_MainUI", u"Stock Tip", None))
        self.m_tabWidgetMain.setTabText(self.m_tabWidgetMain.indexOf(self.m_tabIndividualFundFlow_DC), QCoreApplication.translate("m_MainUI", u"IndividualFundFlow_DC", None))
        self.m_tabWidgetMain.setTabText(self.m_tabWidgetMain.indexOf(self.m_tabIndividualFundFlow_XQ), QCoreApplication.translate("m_MainUI", u"IndividualFundFlow_XQ", None))
        self.m_tabWidgetMain.setTabText(self.m_tabWidgetMain.indexOf(self.m_tabFocusStock), QCoreApplication.translate("m_MainUI", u"Focus Stock", None))
        self.m_tabWidgetMarketTeperature.setTabText(self.m_tabWidgetMarketTeperature.indexOf(self.m_tabRisePercent), QCoreApplication.translate("m_MainUI", u"Rise Percent", None))
        self.m_tabWidgetMarketTeperature.setTabText(self.m_tabWidgetMarketTeperature.indexOf(self.m_tabRise2Limit), QCoreApplication.translate("m_MainUI", u"Rise2Limit", None))
        self.m_tabWidgetMain.setTabText(self.m_tabWidgetMain.indexOf(self.m_tabMarketTemperature), QCoreApplication.translate("m_MainUI", u"Market Temperature", None))
    # retranslateUi

