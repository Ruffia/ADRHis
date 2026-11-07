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
        m_MainUI.resize(1102, 701)
        self.m_tabWidgetMain = QTabWidget(m_MainUI)
        self.m_tabWidgetMain.setObjectName(u"m_tabWidgetMain")
        self.m_tabWidgetMain.setGeometry(QRect(10, 10, 1081, 681))
        self.m_tabIndividualFundFlow_DC = QWidget()
        self.m_tabIndividualFundFlow_DC.setObjectName(u"m_tabIndividualFundFlow_DC")
        self.m_tableViewIndividualFundFlow_DC = QTableView(self.m_tabIndividualFundFlow_DC)
        self.m_tableViewIndividualFundFlow_DC.setObjectName(u"m_tableViewIndividualFundFlow_DC")
        self.m_tableViewIndividualFundFlow_DC.setGeometry(QRect(0, 0, 1071, 651))
        self.m_tabWidgetMain.addTab(self.m_tabIndividualFundFlow_DC, "")
        self.m_tabIndividualFundFlow_XQ = QWidget()
        self.m_tabIndividualFundFlow_XQ.setObjectName(u"m_tabIndividualFundFlow_XQ")
        self.m_tableViewIndividualFundFlow_XQ = QTableView(self.m_tabIndividualFundFlow_XQ)
        self.m_tableViewIndividualFundFlow_XQ.setObjectName(u"m_tableViewIndividualFundFlow_XQ")
        self.m_tableViewIndividualFundFlow_XQ.setGeometry(QRect(5, 1, 1061, 641))
        self.m_tabWidgetMain.addTab(self.m_tabIndividualFundFlow_XQ, "")

        self.retranslateUi(m_MainUI)

        self.m_tabWidgetMain.setCurrentIndex(1)


        QMetaObject.connectSlotsByName(m_MainUI)
    # setupUi

    def retranslateUi(self, m_MainUI):
        m_MainUI.setWindowTitle(QCoreApplication.translate("m_MainUI", u"Stock Tip", None))
        self.m_tabWidgetMain.setTabText(self.m_tabWidgetMain.indexOf(self.m_tabIndividualFundFlow_DC), QCoreApplication.translate("m_MainUI", u"IndividualFundFlow_DC", None))
        self.m_tabWidgetMain.setTabText(self.m_tabWidgetMain.indexOf(self.m_tabIndividualFundFlow_XQ), QCoreApplication.translate("m_MainUI", u"IndividualFundFlow_XQ", None))
    # retranslateUi

