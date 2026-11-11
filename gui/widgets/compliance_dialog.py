# gui/widgets/compliance_dialog.py
"""
Dialog mit Format- und Kompatibilitätshinweisen zu einem Video:
Ursache und Folgen auf Hardware-Playern; der Nutzer kann trotzdem fortfahren.
"""

from typing import List, Dict, Any, Optional
from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QFrame
)
from core.translations import tr
from modules.video_tools import warning_text


class ComplianceWarningDialog(QDialog):
    def __init__(
        self,
        title_name: str,
        video_filename: str,
        warnings: List[Dict[str, Any]],
        lang: str = "de",
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.lang = lang
        self.setWindowTitle(tr("compliance_dialog_title", self.lang))
        self.resize(640, 520)
        self.setMinimumSize(540, 400)
        self.setStyleSheet("""
            QDialog {
                background-color: #18181B;
                color: #E4E4E7;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        # Header
        header_layout = QHBoxLayout()
        header_icon = QLabel("⚠️")
        header_icon.setStyleSheet("font-size: 28px;")
        header_layout.addWidget(header_icon)

        header_text_layout = QVBoxLayout()
        title_lbl = QLabel(tr("compliance_header", self.lang, name=title_name))
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #FDE047;")
        file_lbl = QLabel(tr("compliance_file", self.lang, file=video_filename))
        file_lbl.setStyleSheet("font-size: 12px; color: #A1A1AA;")
        header_text_layout.addWidget(title_lbl)
        header_text_layout.addWidget(file_lbl)
        header_layout.addLayout(header_text_layout, stretch=1)
        layout.addLayout(header_layout)

        # Scrollbereich für Warnungen
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("background-color: transparent; border: none;")
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 10, 0)
        scroll_layout.setSpacing(12)

        for w in warnings:
            card = QFrame()
            card.setStyleSheet("""
                QFrame {
                    background-color: #202024;
                    border: 1px solid #3F3F46;
                    border-left: 4px solid #FDE047;
                    border-radius: 6px;
                    padding: 12px;
                }
            """)
            c_layout = QVBoxLayout(card)
            c_layout.setSpacing(8)

            w_title = QLabel(warning_text(w, "title") or tr("compliance_note", self.lang))
            w_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #FAFAFA;")
            c_layout.addWidget(w_title)

            # Issue
            msg = warning_text(w, "message")
            if msg:
                lbl_msg = QLabel(f"<b>{tr('compliance_header_issue', self.lang)}</b><br>{msg}")
                lbl_msg.setWordWrap(True)
                lbl_msg.setStyleSheet("color: #D4D4D8; font-size: 12px; line-height: 1.4;")
                c_layout.addWidget(lbl_msg)

            # Consequence
            cons = warning_text(w, "consequence")
            if cons:
                lbl_cons = QLabel(f"<b>{tr('compliance_header_consequence', self.lang)}</b><br>{cons}")
                lbl_cons.setWordWrap(True)
                lbl_cons.setStyleSheet("color: #FCD34D; font-size: 12px; line-height: 1.4;")
                c_layout.addWidget(lbl_cons)

            # Recommendation
            recom = warning_text(w, "recommendation")
            if recom:
                lbl_recom = QLabel(f"<b>{tr('compliance_header_recommendation', self.lang)}</b><br>{recom}")
                lbl_recom.setWordWrap(True)
                lbl_recom.setStyleSheet("color: #A1A1AA; font-size: 12px; line-height: 1.4;")
                c_layout.addWidget(lbl_recom)

            scroll_layout.addWidget(card)

        scroll_layout.addStretch(1)
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area, stretch=1)

        # Info Note
        note_lbl = QLabel(tr("compliance_footer", self.lang))
        note_lbl.setWordWrap(True)
        note_lbl.setStyleSheet("color: #71717A; font-size: 11px; font-style: italic;")
        layout.addWidget(note_lbl)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)

        self.btn_close = QPushButton(tr("compliance_btn_close", self.lang))
        self.btn_close.setFixedHeight(34)
        self.btn_close.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px solid #3F3F46;
                color: #D4D4D8;
                border-radius: 6px;
                padding: 0 16px;
            }
            QPushButton:hover {
                background-color: #27272A;
                color: #FAFAFA;
            }
        """)
        self.btn_close.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_close)

        self.btn_ignore = QPushButton("✓ " + tr("compliance_btn_ignore", self.lang))
        self.btn_ignore.setFixedHeight(34)
        self.btn_ignore.setStyleSheet("""
            QPushButton {
                background-color: #FBBF24;
                border: 1px solid #FBBF24;
                color: #18181B;
                font-weight: bold;
                border-radius: 6px;
                padding: 0 16px;
            }
            QPushButton:hover {
                background-color: #FCD34D;
            }
        """)
        self.btn_ignore.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_ignore)

        layout.addLayout(btn_layout)
