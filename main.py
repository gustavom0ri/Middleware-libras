"""
Interface principal - Middleware Libras
"""

import sys
import os

try:
    import torch
    torch_dir = os.path.join(os.path.dirname(torch.__file__), "lib")
    if os.path.isdir(torch_dir):
        os.add_dll_directory(torch_dir)
except Exception:
    pass

from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401

import queue
import threading
import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QTextEdit, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread
from PyQt6.QtGui import QTextCursor

DARK = {
    "bg":           "#0D0D0D",
    "bg2":          "#111111",
    "bg3":          "#080808",
    "border":       "#1E1E1E",
    "border2":      "#141414",
    "accent":       "#00FF88",
    "accent_dim":   "#00FF8844",
    "accent_bg":    "#0A2A1A",
    "danger":       "#FF4466",
    "danger_dim":   "#FF446644",
    "danger_bg":    "#1A0A0F",
    "text":         "#C8C8C8",
    "text_dim":     "#444444",
    "text_muted":   "#252525",
    "text_title":   "#E0E0E0",
    "status_bg":    "#1A1A1A",
    "status_text":  "#555555",
    "status_border":"#2A2A2A",
    "scroll":       "#2A2A2A",
    "combo_bg":     "#1A1A1A",
    "combo_text":   "#CCCCCC",
    "ts_color":     "#333333",
}

LIGHT = {
    "bg":           "#F5F5F0",
    "bg2":          "#EBEBЕ6",
    "bg2":          "#E8E8E3",
    "bg3":          "#FFFFFF",
    "border":       "#DDDDDD",
    "border2":      "#E5E5E5",
    "accent":       "#00AA66",
    "accent_dim":   "#00AA6633",
    "accent_bg":    "#E0F5EC",
    "danger":       "#DD2244",
    "danger_dim":   "#DD224433",
    "danger_bg":    "#FDE8EC",
    "text":         "#222222",
    "text_dim":     "#888888",
    "text_muted":   "#BBBBBB",
    "text_title":   "#111111",
    "status_bg":    "#EEEEEE",
    "status_text":  "#999999",
    "status_border":"#DDDDDD",
    "scroll":       "#CCCCCC",
    "combo_bg":     "#FFFFFF",
    "combo_text":   "#333333",
    "ts_color":     "#AAAAAA",
}


def build_stylesheet(t: dict) -> str:
    return f"""
* {{
    font-family: 'Consolas', 'Courier New', monospace;
    color: {t['text_title']};
}}
QMainWindow, QWidget#root {{
    background-color: {t['bg']};
}}
QWidget#topbar {{
    background-color: {t['bg']};
    border-bottom: 1px solid {t['border']};
}}
QLabel#app_title {{
    font-size: 13px;
    font-weight: bold;
    color: {t['accent']};
    letter-spacing: 3px;
}}
QLabel#app_subtitle {{
    font-size: 11px;
    color: {t['text_dim']};
    letter-spacing: 1px;
}}
QLabel#status_idle {{
    background-color: {t['status_bg']};
    color: {t['status_text']};
    font-size: 10px;
    letter-spacing: 2px;
    border: 1px solid {t['status_border']};
    border-radius: 10px;
    padding: 3px 12px;
}}
QLabel#status_running {{
    background-color: {t['accent_bg']};
    color: {t['accent']};
    font-size: 10px;
    letter-spacing: 2px;
    border: 1px solid {t['accent_dim']};
    border-radius: 10px;
    padding: 3px 12px;
}}
QWidget#config_panel {{
    background-color: {t['bg2']};
    border: 1px solid {t['border']};
    border-radius: 8px;
}}
QLabel#config_label {{
    font-size: 10px;
    color: {t['text_dim']};
    letter-spacing: 2px;
}}
QComboBox {{
    background-color: {t['combo_bg']};
    border: 1px solid {t['border']};
    border-radius: 5px;
    padding: 6px 12px;
    font-size: 12px;
    color: {t['combo_text']};
    min-width: 200px;
}}
QComboBox:hover {{ border-color: {t['accent_dim']}; }}
QComboBox::drop-down {{ border: none; padding-right: 8px; }}
QComboBox QAbstractItemView {{
    background-color: {t['combo_bg']};
    border: 1px solid {t['border']};
    selection-background-color: {t['accent_bg']};
    selection-color: {t['accent']};
}}
QWidget#terminal_container {{
    background-color: {t['bg3']};
    border: 1px solid {t['border']};
    border-radius: 8px;
}}
QLabel#terminal_header {{
    font-size: 10px;
    color: {t['text_dim']};
    letter-spacing: 2px;
    padding: 8px 16px 4px 16px;
    border-bottom: 1px solid {t['border2']};
}}
QTextEdit#terminal {{
    background-color: {t['bg3']};
    border: none;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 13px;
    color: {t['text']};
    padding: 12px 16px;
    selection-background-color: {t['accent_bg']};
}}
QScrollBar:vertical {{
    background: {t['bg']};
    width: 6px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {t['scroll']};
    border-radius: 3px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QPushButton#btn_start {{
    background-color: {t['accent']};
    color: #000000;
    border: none;
    border-radius: 6px;
    font-size: 12px;
    font-weight: bold;
    letter-spacing: 2px;
    padding: 10px 28px;
    min-width: 120px;
}}
QPushButton#btn_start:hover {{ background-color: {t['accent']}CC; }}
QPushButton#btn_start:pressed {{ background-color: {t['accent']}99; }}
QPushButton#btn_stop {{
    background-color: transparent;
    color: {t['danger']};
    border: 1px solid {t['danger_dim']};
    border-radius: 6px;
    font-size: 12px;
    letter-spacing: 2px;
    padding: 10px 28px;
    min-width: 120px;
}}
QPushButton#btn_stop:hover {{
    background-color: {t['danger_bg']};
    border-color: {t['danger']};
}}
QPushButton#btn_stop:disabled {{
    color: {t['text_dim']};
    border-color: {t['border']};
}}
QPushButton#btn_secondary {{
    background-color: transparent;
    color: {t['text_dim']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    font-size: 11px;
    letter-spacing: 1px;
    padding: 10px 20px;
}}
QPushButton#btn_secondary:hover {{
    color: {t['text']};
    border-color: {t['text_dim']};
}}
QPushButton#btn_theme {{
    background-color: transparent;
    color: {t['text_dim']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    font-size: 13px;
    padding: 8px 14px;
    min-width: 36px;
}}
QPushButton#btn_theme:hover {{
    color: {t['text']};
    border-color: {t['text_dim']};
}}
QLabel#footer {{
    font-size: 10px;
    color: {t['text_muted']};
    letter-spacing: 1px;
}}
"""


class TranscriptionWorker(QObject):
    text_received = pyqtSignal(str)
    glosa_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, model_name: str):
        super().__init__()
        self.model_name = model_name
        self._capture = None
        self._stt = None
        self._translator = None
        self._running = False

    def start_transcription(self):
        try:
            from layers.audio_capture import AudioCapture
            from layers.speech_to_text import SpeechToText
            from layers.vlibras_translator import VLibrasTranslator

            self._stt = SpeechToText(model_name=self.model_name)
            self._stt.load()

            self._capture = AudioCapture(chunk_seconds=3)
            self._capture.start()
            self._stt.start(self._capture.audio_queue)

            self._translator = VLibrasTranslator()
            self._translator.start(self._stt.text_queue)

            self._running = True

            def consume_glosa():
                while self._running:
                    glosa = self._translator.get_glosa(timeout=1.0)
                    if glosa:
                        self.glosa_received.emit(glosa)

            threading.Thread(target=consume_glosa, daemon=True).start()

            while self._running:
                text = self._stt.get_text(timeout=1.0)
                if text:
                    self.text_received.emit(text)

        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            self._cleanup()
            self.finished.emit()

    def stop(self):
        self._running = False

    def _cleanup(self):
        if self._translator:
            self._translator.stop()
        if self._stt:
            self._stt.stop()
        if self._capture:
            self._capture.stop()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LIBRAS MIDDLEWARE")
        self.setMinimumSize(720, 560)
        self.resize(820, 620)
        self._worker = None
        self._thread = None
        self._is_running = False
        self._chunk_count = 0
        self._avatar_window = None
        self._dark_mode = True
        self._setup_ui()
        self._setup_blink_timer()
        self._apply_theme()

    def _setup_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(14)

        layout.addWidget(self._build_topbar())
        layout.addWidget(self._build_config_panel())
        layout.addWidget(self._build_terminal(), stretch=1)
        layout.addWidget(self._build_controls())
        layout.addWidget(self._build_footer())

    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("topbar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(0, 0, 0, 10)

        title = QLabel("LIBRAS MIDDLEWARE")
        title.setObjectName("app_title")

        subtitle = QLabel("v0.1.0 — audio → text → libras")
        subtitle.setObjectName("app_subtitle")

        self._status_label = QLabel("● IDLE")
        self._status_label.setObjectName("status_idle")

        self._btn_theme = QPushButton("☀")
        self._btn_theme.setObjectName("btn_theme")
        self._btn_theme.setToolTip("Alternar tema claro/escuro")
        self._btn_theme.clicked.connect(self._toggle_theme)

        h.addWidget(title)
        h.addSpacing(12)
        h.addWidget(subtitle)
        h.addStretch()
        h.addWidget(self._status_label)
        h.addSpacing(8)
        h.addWidget(self._btn_theme)
        return bar

    def _build_config_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("config_panel")
        h = QHBoxLayout(panel)
        h.setContentsMargins(16, 12, 16, 12)

        lbl = QLabel("MODELO WHISPER")
        lbl.setObjectName("config_label")

        self._model_combo = QComboBox()
        self._model_combo.addItems([
            "small  —  rapido  (~460MB, recomendado)",
            "medium —  preciso (~1.5GB, PCs potentes)",
            "tiny   —  leve    (~75MB, baixa acuracia)",
            "base   —  basico  (~145MB)",
        ])

        h.addWidget(lbl)
        h.addSpacing(12)
        h.addWidget(self._model_combo)
        h.addStretch()
        return panel

    def _build_terminal(self) -> QWidget:
        container = QWidget()
        container.setObjectName("terminal_container")
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        header = QLabel("OUTPUT  /  TRANSCRICAO EM TEMPO REAL")
        header.setObjectName("terminal_header")
        v.addWidget(header)

        self._terminal = QTextEdit()
        self._terminal.setObjectName("terminal")
        self._terminal.setReadOnly(True)
        self._terminal.setPlaceholderText(
            "// aguardando inicio da transcricao...\n"
            "// pressione START para comecar"
        )
        v.addWidget(self._terminal)
        return container

    def _build_controls(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        self._btn_start = QPushButton("▶  START")
        self._btn_start.setObjectName("btn_start")
        self._btn_start.clicked.connect(self._on_start)

        self._btn_stop = QPushButton("■  STOP")
        self._btn_stop.setObjectName("btn_stop")
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._on_stop)

        self._btn_avatar = QPushButton("◉  AVATAR")
        self._btn_avatar.setObjectName("btn_secondary")
        self._btn_avatar.clicked.connect(self._toggle_avatar)

        self._btn_retry = QPushButton("↺")
        self._btn_retry.setObjectName("btn_secondary")
        self._btn_retry.setToolTip("Reiniciar avatar (limpa cache e cookies)")
        self._btn_retry.setFixedWidth(36)
        self._btn_retry.setEnabled(False)
        self._btn_retry.clicked.connect(self._retry_avatar)

        self._btn_clear = QPushButton("LIMPAR")
        self._btn_clear.setObjectName("btn_secondary")
        self._btn_clear.clicked.connect(self._terminal.clear)

        h.addWidget(self._btn_start)
        h.addSpacing(8)
        h.addWidget(self._btn_stop)
        h.addStretch()
        h.addWidget(self._btn_avatar)
        h.addSpacing(4)
        h.addWidget(self._btn_retry)
        h.addSpacing(8)
        h.addWidget(self._btn_clear)
        return w

    def _build_footer(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        self._footer_label = QLabel("pronto.")
        self._footer_label.setObjectName("footer")

        self._chunk_label = QLabel("")
        self._chunk_label.setObjectName("footer")

        h.addWidget(self._footer_label)
        h.addStretch()
        h.addWidget(self._chunk_label)
        return w

    def _setup_blink_timer(self):
        self._blink_state = False
        self._blink_timer = QTimer()
        self._blink_timer.setInterval(600)
        self._blink_timer.timeout.connect(self._blink_cursor)

    def _blink_cursor(self):
        if not self._is_running:
            return
        self._blink_state = not self._blink_state
        char = "█" if self._blink_state else " "
        self._footer_label.setText(f"ouvindo {char}")

    def _toggle_theme(self):
        self._dark_mode = not self._dark_mode
        self._apply_theme()

    def _apply_theme(self):
        t = DARK if self._dark_mode else LIGHT
        QApplication.instance().setStyleSheet(build_stylesheet(t))
        self._btn_theme.setText("☀" if self._dark_mode else "🌙")
        self._ts_color  = t["ts_color"]
        self._acc_color = t["accent"]
        self._txt_color = t["text"]

    def _get_model_name(self) -> str:
        return self._model_combo.currentText().split()[0].strip()

    def _on_start(self):
        model = self._get_model_name()
        self._log_system(f"iniciando modelo '{model}'... aguarde.")
        self._set_running(True)

        self._worker = TranscriptionWorker(model_name=model)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.start_transcription)
        self._worker.text_received.connect(self._on_text)
        self._worker.glosa_received.connect(self._on_glosa)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(lambda: self._set_running(False))

        self._thread.start()

    def _on_stop(self):
        if self._worker:
            self._worker.stop()
        self._log_system("transcricao encerrada.")

    def _set_running(self, running: bool):
        self._is_running = running
        self._btn_start.setEnabled(not running)
        self._btn_stop.setEnabled(running)
        self._model_combo.setEnabled(not running)

        if running:
            self._status_label.setObjectName("status_running")
            self._status_label.setText("● LIVE")
            self._blink_timer.start()
        else:
            self._status_label.setObjectName("status_idle")
            self._status_label.setText("● IDLE")
            self._blink_timer.stop()
            self._footer_label.setText("pronto.")

        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)

    def _toggle_avatar(self):
        from layers.avatar_window import AvatarWindow
        if self._avatar_window is None:
            self._avatar_window = AvatarWindow()
            self._avatar_window.show()
            self._btn_avatar.setText("◎  AVATAR")
            self._btn_retry.setEnabled(True)
            self._log_system("avatar iniciado — arraste para posicionar.")
        else:
            self._avatar_window.close()
            self._avatar_window = None
            self._btn_avatar.setText("◉  AVATAR")
            self._btn_retry.setEnabled(False)
            self._log_system("avatar fechado.")

    def _retry_avatar(self):
        if self._avatar_window:
            self._avatar_window.retry()
            self._log_system("avatar reiniciado — aguarde carregar...")

    def _on_glosa(self, glosa: str):
        if self._avatar_window:
            self._avatar_window.translate(glosa)

    def _on_text(self, text: str):
        self._chunk_count += 1
        self._chunk_label.setText(f"{self._chunk_count} chunks")
        cursor = self._terminal.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        cursor.insertHtml(
            f'<span style="color:{self._ts_color};font-size:11px;">[{ts}]</span> '
            f'<span style="color:{self._acc_color};">▸</span> '
            f'<span style="color:{self._txt_color};">{text}</span><br>'
        )
        self._terminal.setTextCursor(cursor)
        self._terminal.ensureCursorVisible()

    def _on_error(self, error: str):
        self._log_system(f"ERRO: {error}", color="#FF4466")

    def _log_system(self, msg: str, color: str = None):
        if color is None:
            color = self._ts_color if hasattr(self, '_ts_color') else "#444"
        cursor = self._terminal.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(f'<span style="color:{color};font-size:11px;">// {msg}</span><br>')
        self._terminal.setTextCursor(cursor)
        self._terminal.ensureCursorVisible()

    def closeEvent(self, event):
        if self._worker:
            self._worker.stop()
        if self._avatar_window:
            self._avatar_window.close()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())