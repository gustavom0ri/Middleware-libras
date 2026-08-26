# -*- coding: utf-8 -*-
"""
avatar_controls.py
==================
Barra de controles do avatar (velocidade + troca de avatar + reiniciar)
para ser usada no main.py.

COMO USAR NO main.py
--------------------
    from Layers.avatar_controls import AvatarControls

    # depois de criar o avatar:
    avatar = AvatarWindow()
    avatar.show()

    controls = AvatarControls(avatar)
    controls.show()          # janela propria
    # OU, se voce tem um layout na sua janela principal:
    # meu_layout.addWidget(controls)

Requer que o avatar_window.py tenha os metodos set_speed(), set_avatar()
e reload_avatar() (ver PATCH_avatar_window.md).
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider,
    QComboBox, QPushButton, QGroupBox
)
from PyQt6.QtCore import Qt


# Avatares oficiais do VLibras.
AVATARES = [
    ("Ícaro",  "icaro"),
    ("Hosana", "hosana"),
    ("Guga",   "guga"),
]

# Velocidades disponiveis (o slider trabalha em decimos: 5 = 0.5x).
SPEED_MIN = 5      # 0.5x
SPEED_MAX = 30     # 3.0x
SPEED_DEFAULT = 20  # 2.0x


class AvatarControls(QWidget):
    """Painel de controle do avatar VLibras."""

    def __init__(self, avatar_window, parent=None):
        super().__init__(parent)
        self._avatar = avatar_window
        self.setWindowTitle("Controles do Avatar")
        self.setMinimumWidth(320)
        self._build_ui()
        self._apply_style()

    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        # ---------------- Velocidade ----------------
        box_speed = QGroupBox("Velocidade da tradução")
        lay_speed = QVBoxLayout(box_speed)

        row = QHBoxLayout()
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(SPEED_MIN)
        self._slider.setMaximum(SPEED_MAX)
        self._slider.setValue(SPEED_DEFAULT)
        self._slider.setTickInterval(5)
        self._slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._slider.valueChanged.connect(self._on_speed_changed)

        self._lbl_speed = QLabel("2.0x")
        self._lbl_speed.setMinimumWidth(48)
        self._lbl_speed.setAlignment(Qt.AlignmentFlag.AlignCenter)

        row.addWidget(self._slider, stretch=1)
        row.addWidget(self._lbl_speed)
        lay_speed.addLayout(row)

        # Atalhos rapidos
        row_btns = QHBoxLayout()
        for label, val in (("0.5x", 5), ("1x", 10), ("1.5x", 15),
                           ("2x", 20), ("3x", 30)):
            b = QPushButton(label)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, v=val: self._slider.setValue(v))
            row_btns.addWidget(b)
        lay_speed.addLayout(row_btns)

        root.addWidget(box_speed)

        # ---------------- Avatar ----------------
        box_av = QGroupBox("Avatar intérprete")
        lay_av = QHBoxLayout(box_av)

        self._combo = QComboBox()
        for nome, valor in AVATARES:
            self._combo.addItem(nome, valor)
        self._combo.setCurrentIndex(0)
        self._combo.currentIndexChanged.connect(self._on_avatar_changed)

        lay_av.addWidget(QLabel("Personagem:"))
        lay_av.addWidget(self._combo, stretch=1)
        root.addWidget(box_av)

        # ---------------- Acoes ----------------
        row_act = QHBoxLayout()
        self._btn_reload = QPushButton("↻  Reiniciar avatar")
        self._btn_reload.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_reload.clicked.connect(self._on_reload)
        row_act.addWidget(self._btn_reload)

        self._btn_test = QPushButton("▶  Testar")
        self._btn_test.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_test.clicked.connect(self._on_test)
        row_act.addWidget(self._btn_test)
        root.addLayout(row_act)

        # ---------------- Status ----------------
        self._status = QLabel("Pronto.")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color:#7f8c99; font-size:11px;")
        root.addWidget(self._status)

    def _apply_style(self):
        self.setStyleSheet("""
            QWidget { background:#141e28; color:#e6edf3;
                      font-family:'Segoe UI'; font-size:12px; }
            QGroupBox { border:1px solid #24333f; border-radius:8px;
                        margin-top:10px; padding:10px; font-weight:600; }
            QGroupBox::title { subcontrol-origin: margin; left:10px;
                               padding:0 4px; color:#00d982; }
            QPushButton { background:#1d2b38; border:1px solid #2c3e50;
                          border-radius:6px; padding:6px 10px; }
            QPushButton:hover { background:#264056; border-color:#00d982; }
            QPushButton:pressed { background:#16222d; }
            QComboBox { background:#1d2b38; border:1px solid #2c3e50;
                        border-radius:6px; padding:5px 8px; }
            QComboBox QAbstractItemView { background:#1d2b38;
                        selection-background-color:#00d982;
                        selection-color:#04121b; }
            QSlider::groove:horizontal { height:5px; background:#24333f;
                        border-radius:3px; }
            QSlider::handle:horizontal { background:#00d982; width:15px;
                        margin:-6px 0; border-radius:8px; }
            QSlider::sub-page:horizontal { background:#00a862;
                        border-radius:3px; }
        """)

    # ------------------------------------------------------------------
    # HANDLERS
    # ------------------------------------------------------------------
    def _on_speed_changed(self, value):
        speed = value / 10.0
        self._lbl_speed.setText(f"{speed:.1f}x")
        if hasattr(self._avatar, "set_speed"):
            self._avatar.set_speed(speed)
            self._status.setText(f"Velocidade ajustada para {speed:.1f}x.")
        else:
            self._status.setText("AvatarWindow.set_speed() nao encontrado — "
                                 "aplique o patch.")

    def _on_avatar_changed(self, index):
        nome = self._combo.itemText(index)
        valor = self._combo.itemData(index)
        if hasattr(self._avatar, "set_avatar"):
            self._avatar.set_avatar(valor)
            self._status.setText(f"Avatar alterado para {nome}. "
                                 f"A troca pode levar alguns segundos.")
        else:
            self._status.setText("AvatarWindow.set_avatar() nao encontrado — "
                                 "aplique o patch.")

    def _on_reload(self):
        self._status.setText("Reiniciando o avatar...")
        if hasattr(self._avatar, "reload_avatar"):
            self._avatar.reload_avatar()
        elif hasattr(self._avatar, "retry"):
            self._avatar.retry()
        # Reaplica as preferencias atuais apos o recarregamento.
        self._status.setText("Avatar reiniciado. Reaplicando preferencias...")

    def _on_test(self):
        if hasattr(self._avatar, "translate"):
            self._avatar.translate("OLA, TESTE DE TRADUCAO")
            self._status.setText("Frase de teste enviada.")

    # ------------------------------------------------------------------
    def current_speed(self):
        return self._slider.value() / 10.0

    def current_avatar(self):
        return self._combo.currentData()
