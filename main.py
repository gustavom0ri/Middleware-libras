"""
Interface principal - Middleware Libras
=======================================
Fluxo de navegacao:

    [ Tela de Selecao de Modo ]
        |-> Audio  -> Libras   (captura audio -> texto -> avatar VLibras)
        |-> Libras -> Audio    (camera -> reconhecimento -> texto -> voz)

Toda a logica original do fluxo "Audio -> Libras" foi preservada.
As mudancas sao de experiencia (selecao de modo, tema, acessibilidade e
consistencia visual).
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

import threading
import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QTextEdit, QStackedWidget, QFrame
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread
from PyQt6.QtGui import QTextCursor, QImage, QPixmap


# =====================================================================
#  TEMAS  (design tokens)
# =====================================================================
# Aparencia consistente: a mesma chave existe nos dois temas e alimenta
# TODOS os componentes, garantindo identidade visual unica.

DARK = {
    "bg":            "#0D0D0D",
    "bg2":           "#141414",   # cards / paineis
    "bg3":           "#080808",   # terminal / campos
    "surface":       "#161616",   # cards da tela inicial
    "surface_hover": "#1E1E1E",
    "border":        "#2A2A2A",
    "border2":       "#1A1A1A",
    "border_strong": "#3A3A3A",
    "accent":        "#00FF88",
    "accent_dim":    "#00FF8844",
    "accent_bg":     "#0A2A1A",
    "accent_text":   "#000000",   # texto sobre o accent
    "info":          "#4AA8FF",
    "info_bg":       "#0A1A2A",
    "danger":        "#FF4466",
    "danger_dim":    "#FF446644",
    "danger_bg":     "#1A0A0F",
    "text":          "#DADADA",   # texto principal / corpo
    "text_dim":      "#9A9A9A",   # texto secundario (legivel)
    "text_muted":    "#6A6A6A",   # rodape / dicas
    "text_title":    "#F2F2F2",   # titulos
    "status_bg":     "#1A1A1A",
    "status_text":   "#B0B0B0",
    "status_border": "#2A2A2A",
    "scroll":        "#2E2E2E",
    "combo_bg":      "#1A1A1A",
    "combo_text":    "#E4E4E4",
    "ts_color":      "#6A6A6A",
}

LIGHT = {
    # Tema claro de ALTO CONTRASTE: preto forte para leitura confortavel.
    "bg":            "#F4F5F7",   # fundo geral (cinza muito claro, sem brilho)
    "bg2":           "#FFFFFF",   # cards / paineis
    "bg3":           "#FFFFFF",   # terminal / campos
    "surface":       "#FFFFFF",   # cards da tela inicial
    "surface_hover": "#EEF6F1",
    "border":        "#C4C9D2",   # borda visivel (contraste real)
    "border2":       "#D9DDE4",
    "border_strong": "#0A0A0A",   # borda de elemento selecionado
    "accent":        "#0E8F52",   # verde escuro (contraste com texto branco)
    "accent_dim":    "#0E8F5255",
    "accent_bg":     "#E2F4EB",
    "accent_text":   "#FFFFFF",   # texto sobre o accent
    "info":          "#0B5FB0",
    "info_bg":       "#E4EEFA",
    "danger":        "#C41E3A",
    "danger_dim":    "#C41E3A55",
    "danger_bg":     "#FBE7EB",
    "text":          "#0A0A0A",   # texto principal (quase #000000)
    "text_dim":      "#3A414D",   # texto secundario (cinza escuro legivel)
    "text_muted":    "#55606E",   # rodape / dicas
    "text_title":    "#000000",   # titulos (preto puro)
    "status_bg":     "#EAECEF",
    "status_text":   "#1A1F27",
    "status_border": "#B8BDC7",
    "scroll":        "#AAB0BA",
    "combo_bg":      "#FFFFFF",
    "combo_text":    "#0A0A0A",
    "ts_color":      "#55606E",
}


def build_stylesheet(t: dict) -> str:
    """Folha de estilo global. Todos os componentes derivam dos mesmos tokens."""
    return f"""
* {{
    font-family: 'Segoe UI', 'Inter', 'Consolas', sans-serif;
    color: {t['text_title']};
}}
QMainWindow, QWidget#root, QStackedWidget {{
    background-color: {t['bg']};
}}

/* ------------------------- TOP BAR ------------------------- */
QWidget#topbar {{
    background-color: {t['bg']};
    border-bottom: 1px solid {t['border']};
}}
QLabel#app_title {{
    font-size: 15px;
    font-weight: 700;
    color: {t['accent']};
    letter-spacing: 2px;
}}
QLabel#app_subtitle {{
    font-size: 12px;
    color: {t['text_dim']};
    letter-spacing: 1px;
}}
QLabel#screen_title {{
    font-size: 16px;
    font-weight: 700;
    color: {t['text_title']};
    letter-spacing: 1px;
}}

/* ------------------------- STATUS ------------------------- */
QLabel#status_idle {{
    background-color: {t['status_bg']};
    color: {t['status_text']};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
    border: 1px solid {t['status_border']};
    border-radius: 12px;
    padding: 5px 14px;
}}
QLabel#status_running {{
    background-color: {t['accent_bg']};
    color: {t['accent']};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    border: 1px solid {t['accent_dim']};
    border-radius: 12px;
    padding: 5px 14px;
}}
QLabel#status_loading {{
    background-color: {t['info_bg']};
    color: {t['info']};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    border: 1px solid {t['info']};
    border-radius: 12px;
    padding: 5px 14px;
}}

/* ------------------------- TELA INICIAL ------------------------- */
QLabel#welcome_title {{
    font-size: 30px;
    font-weight: 800;
    color: {t['text_title']};
    letter-spacing: 1px;
}}
QLabel#welcome_subtitle {{
    font-size: 15px;
    color: {t['text_dim']};
}}
QLabel#welcome_hint {{
    font-size: 12px;
    color: {t['text_muted']};
}}

/* Cartao de modo (opcao grande e destacada) */
QPushButton#mode_card {{
    background-color: {t['surface']};
    border: 2px solid {t['border']};
    border-radius: 16px;
    text-align: left;
    padding: 4px;
}}
QPushButton#mode_card:hover {{
    background-color: {t['surface_hover']};
    border-color: {t['accent']};
}}
QPushButton#mode_card:focus {{
    border: 2px solid {t['accent']};
    outline: none;
}}
QLabel#card_icon   {{ font-size: 46px; background: transparent; }}
QLabel#card_title  {{ font-size: 20px; font-weight: 700; color: {t['text_title']}; background: transparent; }}
QLabel#card_desc   {{ font-size: 13px; color: {t['text_dim']}; background: transparent; }}
QLabel#card_arrow  {{ font-size: 24px; color: {t['accent']}; background: transparent; }}

/* ------------------------- PAINEL DE CONFIG ------------------------- */
QWidget#config_panel {{
    background-color: {t['bg2']};
    border: 1px solid {t['border']};
    border-radius: 10px;
}}
QLabel#config_label {{
    font-size: 11px;
    font-weight: 600;
    color: {t['text_dim']};
    letter-spacing: 1px;
}}
QComboBox {{
    background-color: {t['combo_bg']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    padding: 9px 14px;
    font-size: 13px;
    color: {t['combo_text']};
    min-width: 240px;
    min-height: 20px;
}}
QComboBox:hover  {{ border-color: {t['accent']}; }}
QComboBox:focus  {{ border: 2px solid {t['accent']}; }}
QComboBox::drop-down {{ border: none; padding-right: 10px; }}
QComboBox QAbstractItemView {{
    background-color: {t['combo_bg']};
    color: {t['combo_text']};
    border: 1px solid {t['border']};
    selection-background-color: {t['accent_bg']};
    selection-color: {t['accent']};
    padding: 4px;
}}

/* ------------------------- TERMINAL ------------------------- */
QWidget#terminal_container {{
    background-color: {t['bg3']};
    border: 1px solid {t['border']};
    border-radius: 10px;
}}
QLabel#terminal_header {{
    font-size: 11px;
    font-weight: 600;
    color: {t['text_dim']};
    letter-spacing: 1px;
    padding: 10px 16px 6px 16px;
    border-bottom: 1px solid {t['border2']};
}}
QTextEdit#terminal {{
    background-color: {t['bg3']};
    border: none;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 14px;
    color: {t['text']};
    padding: 14px 16px;
    selection-background-color: {t['accent_bg']};
}}

/* ------------------------- CAMERA ------------------------- */
QLabel#camera_preview {{
    background-color: {t['bg3']};
    border: 2px dashed {t['border']};
    border-radius: 10px;
    color: {t['text_dim']};
    font-size: 14px;
}}
QLabel#recognized_header {{
    font-size: 11px;
    font-weight: 600;
    color: {t['text_dim']};
    letter-spacing: 1px;
}}
QTextEdit#recognized {{
    background-color: {t['bg3']};
    border: 1px solid {t['border']};
    border-radius: 10px;
    font-size: 15px;
    color: {t['text']};
    padding: 14px 16px;
}}

/* ------------------------- SCROLLBAR ------------------------- */
QScrollBar:vertical {{
    background: {t['bg']};
    width: 8px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {t['scroll']};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

/* ------------------------- BOTOES ------------------------- */
QPushButton#btn_start {{
    background-color: {t['accent']};
    color: {t['accent_text']};
    border: none;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 13px 30px;
    min-width: 140px;
    min-height: 22px;
}}
QPushButton#btn_start:hover   {{ background-color: {t['accent']}DD; }}
QPushButton#btn_start:pressed {{ background-color: {t['accent']}AA; }}
QPushButton#btn_start:focus   {{ border: 2px solid {t['text_title']}; }}

QPushButton#btn_stop {{
    background-color: transparent;
    color: {t['danger']};
    border: 2px solid {t['danger_dim']};
    border-radius: 8px;
    font-size: 14px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 12px 30px;
    min-width: 140px;
    min-height: 22px;
}}
QPushButton#btn_stop:hover    {{ background-color: {t['danger_bg']}; border-color: {t['danger']}; }}
QPushButton#btn_stop:focus    {{ border: 2px solid {t['danger']}; }}
QPushButton#btn_stop:disabled {{ color: {t['text_muted']}; border-color: {t['border']}; }}

QPushButton#btn_secondary {{
    background-color: transparent;
    color: {t['text']};
    border: 1px solid {t['border']};
    border-radius: 8px;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 1px;
    padding: 12px 22px;
    min-height: 20px;
}}
QPushButton#btn_secondary:hover  {{ color: {t['text_title']}; border-color: {t['accent']}; background-color: {t['accent_bg']}; }}
QPushButton#btn_secondary:focus  {{ border: 2px solid {t['accent']}; }}

QPushButton#btn_back {{
    background-color: transparent;
    color: {t['text']};
    border: 1px solid {t['border']};
    border-radius: 8px;
    font-size: 13px;
    font-weight: 600;
    padding: 9px 18px;
    min-height: 18px;
}}
QPushButton#btn_back:hover  {{ color: {t['text_title']}; border-color: {t['accent']}; }}
QPushButton#btn_back:focus  {{ border: 2px solid {t['accent']}; }}

QPushButton#btn_theme {{
    background-color: transparent;
    color: {t['text']};
    border: 1px solid {t['border']};
    border-radius: 8px;
    font-size: 16px;
    padding: 8px 14px;
    min-width: 40px;
    min-height: 18px;
}}
QPushButton#btn_theme:hover  {{ color: {t['text_title']}; border-color: {t['accent']}; }}
QPushButton#btn_theme:focus  {{ border: 2px solid {t['accent']}; }}

QLabel#footer {{
    font-size: 11px;
    color: {t['text_muted']};
    letter-spacing: 1px;
}}
"""


# =====================================================================
#  COMPONENTE: Cartao de selecao de modo
# =====================================================================
class ModeCard(QPushButton):
    """Opcao grande e destacada da tela inicial (icone + titulo + descricao)."""

    def __init__(self, icon: str, title: str, description: str, parent=None):
        super().__init__(parent)
        self.setObjectName("mode_card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(300, 210)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 22)
        lay.setSpacing(10)

        top = QHBoxLayout()
        ic = QLabel(icon)
        ic.setObjectName("card_icon")
        arrow = QLabel("\u2192")  # seta -> indicador de acao (nao depende de cor)
        arrow.setObjectName("card_arrow")
        arrow.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        top.addWidget(ic)
        top.addStretch()
        top.addWidget(arrow)

        ttl = QLabel(title)
        ttl.setObjectName("card_title")
        ttl.setWordWrap(True)

        desc = QLabel(description)
        desc.setObjectName("card_desc")
        desc.setWordWrap(True)

        lay.addLayout(top)
        lay.addWidget(ttl)
        lay.addWidget(desc)
        lay.addStretch()

        # Cliques atravessam os rotulos internos e chegam ao botao
        for child in (ic, arrow, ttl, desc):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)


# =====================================================================
#  WORKER: Audio -> Libras  (logica original preservada)
# =====================================================================
class TranscriptionWorker(QObject):
    text_received = pyqtSignal(str)
    glosa_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    started = pyqtSignal()
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
            self.started.emit()

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


# =====================================================================
#  WORKER: Libras -> Audio  (camera -> reconhecimento -> texto -> voz)
# =====================================================================
class CameraWorker(QObject):
    """
    Captura frames da webcam e os envia para a UI. A etapa de reconhecimento
    de sinais fica isolada em `_recognize()` para integracao futura do modelo.
    Requer OpenCV (opcional). Sem camera, emite `error_occurred`.
    """
    frame_ready = pyqtSignal(QImage)
    text_recognized = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._running = False

    def start_capture(self):
        try:
            import cv2  # dependencia opcional
        except Exception:
            self.error_occurred.emit(
                "OpenCV nao encontrado. Instale com:  pip install opencv-python"
            )
            self.finished.emit()
            return

        cap = cv2.VideoCapture(0)
        if not cap or not cap.isOpened():
            self.error_occurred.emit(
                "Nao foi possivel acessar a webcam. Verifique a camera e as permissoes."
            )
            self.finished.emit()
            return

        self._running = True
        try:
            while self._running:
                ok, frame = cap.read()
                if not ok:
                    continue
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb.shape
                img = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
                self.frame_ready.emit(img.copy())

                # ---- Ponto de integracao do modelo de reconhecimento ----
                # texto = self._recognize(frame)
                # if texto:
                #     self.text_recognized.emit(texto)
        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            cap.release()
            self.finished.emit()

    def _recognize(self, frame):
        """Placeholder do reconhecedor de sinais (integracao futura)."""
        return None

    def stop(self):
        self._running = False


def speak(text: str):
    """Text-to-Speech opcional (pyttsx3). Silencioso se indisponivel."""
    def _run():
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()


# =====================================================================
#  TELA 1: Selecao de modo
# =====================================================================
class WelcomeScreen(QWidget):
    mode_selected = pyqtSignal(str)   # "audio2libras" | "libras2audio"

    def __init__(self, main):
        super().__init__()
        self.setObjectName("root")
        self._main = main
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- top bar (identidade + tema) ----
        bar = QWidget()
        bar.setObjectName("topbar")
        hb = QHBoxLayout(bar)
        hb.setContentsMargins(28, 14, 28, 14)
        brand = QLabel("LIBRAS MIDDLEWARE")
        brand.setObjectName("app_title")
        self.btn_theme = QPushButton("\u2600")
        self.btn_theme.setObjectName("btn_theme")
        self.btn_theme.setToolTip("Alternar tema claro/escuro")
        self.btn_theme.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_theme.clicked.connect(self._main._toggle_theme)
        hb.addWidget(brand)
        hb.addStretch()
        hb.addWidget(self.btn_theme)
        outer.addWidget(bar)

        # ---- corpo centralizado ----
        body = QVBoxLayout()
        body.setContentsMargins(40, 30, 40, 30)
        body.setSpacing(8)

        title = QLabel("Como voce quer traduzir?")
        title.setObjectName("welcome_title")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        subtitle = QLabel("Escolha o modo de traducao para comecar")
        subtitle.setObjectName("welcome_subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        body.addStretch()
        body.addWidget(title)
        body.addWidget(subtitle)
        body.addSpacing(28)

        # ---- os dois cartoes ----
        cards = QHBoxLayout()
        cards.setSpacing(24)
        cards.addStretch()

        card_a = ModeCard(
            "\U0001F50A",  # 🔊
            "\u00C1udio  \u2192  Libras",
            "Captura o \u00e1udio do sistema, converte em texto e exibe a "
            "tradu\u00e7\u00e3o em Libras pelo avatar VLibras.",
        )
        card_a.clicked.connect(lambda: self.mode_selected.emit("audio2libras"))

        card_b = ModeCard(
            "\U0001F91F",  # 🤟
            "Libras  \u2192  \u00C1udio",
            "Usa a c\u00e2mera para interpretar os sinais em Libras, converte "
            "em texto e reproduz o resultado em voz.",
        )
        card_b.clicked.connect(lambda: self.mode_selected.emit("libras2audio"))

        cards.addWidget(card_a)
        cards.addWidget(card_b)
        cards.addStretch()
        body.addLayout(cards)

        body.addSpacing(22)
        hint = QLabel("\U0001F4A1  Voc\u00ea pode trocar de modo a qualquer momento.")
        hint.setObjectName("welcome_hint")
        hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        body.addWidget(hint)
        body.addStretch()

        outer.addLayout(body, stretch=1)

    def apply_theme_colors(self, t: dict):
        self.btn_theme.setText("\u2600" if self._main._dark_mode else "\U0001F319")


# =====================================================================
#  TELA 2: Audio -> Libras  (fluxo original, visual modernizado)
# =====================================================================
class AudioToLibrasScreen(QWidget):
    back_requested = pyqtSignal()

    def __init__(self, main):
        super().__init__()
        self.setObjectName("root")
        self._main = main
        self._worker = None
        self._thread = None
        self._is_running = False
        self._chunk_count = 0
        self._avatar_window = None
        self._ts_color = DARK["ts_color"]
        self._acc_color = DARK["accent"]
        self._txt_color = DARK["text"]
        self._build_ui()
        self._setup_blink_timer()

    # ---------------------------- UI ----------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(16)
        layout.addWidget(self._build_topbar())
        layout.addWidget(self._build_config_panel())
        layout.addWidget(self._build_terminal(), stretch=1)
        layout.addWidget(self._build_controls())
        layout.addWidget(self._build_footer())

    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("topbar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(0, 0, 0, 12)

        self._btn_back = QPushButton("\u2190  Voltar")
        self._btn_back.setObjectName("btn_back")
        self._btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_back.clicked.connect(self._on_back)

        title = QLabel("\U0001F50A  \u00C1udio \u2192 Libras")
        title.setObjectName("screen_title")

        self._status_label = QLabel("\u25CF  Ocioso")
        self._status_label.setObjectName("status_idle")

        self.btn_theme = QPushButton("\u2600")
        self.btn_theme.setObjectName("btn_theme")
        self.btn_theme.setToolTip("Alternar tema claro/escuro")
        self.btn_theme.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_theme.clicked.connect(self._main._toggle_theme)

        h.addWidget(self._btn_back)
        h.addSpacing(14)
        h.addWidget(title)
        h.addStretch()
        h.addWidget(self._status_label)
        h.addSpacing(10)
        h.addWidget(self.btn_theme)
        return bar

    def _build_config_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("config_panel")
        h = QHBoxLayout(panel)
        h.setContentsMargins(18, 14, 18, 14)

        lbl = QLabel("MODELO WHISPER")
        lbl.setObjectName("config_label")

        self._model_combo = QComboBox()
        self._model_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._model_combo.addItems([
            "small  \u2014  r\u00e1pido  (~460MB, recomendado)",
            "medium \u2014  preciso (~1.5GB, PCs potentes)",
            "tiny   \u2014  leve    (~75MB, baixa acur\u00e1cia)",
            "base   \u2014  b\u00e1sico  (~145MB)",
        ])

        h.addWidget(lbl)
        h.addSpacing(14)
        h.addWidget(self._model_combo)
        h.addStretch()
        return panel

    def _build_terminal(self) -> QWidget:
        container = QWidget()
        container.setObjectName("terminal_container")
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        header = QLabel("TRANSCRI\u00c7\u00c3O EM TEMPO REAL")
        header.setObjectName("terminal_header")
        v.addWidget(header)

        self._terminal = QTextEdit()
        self._terminal.setObjectName("terminal")
        self._terminal.setReadOnly(True)
        self._terminal.setPlaceholderText(
            "// aguardando in\u00edcio da transcri\u00e7\u00e3o...\n"
            "// pressione INICIAR para come\u00e7ar"
        )
        v.addWidget(self._terminal)
        return container

    def _build_controls(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)

        self._btn_start = QPushButton("\u25B6  INICIAR")
        self._btn_start.setObjectName("btn_start")
        self._btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_start.clicked.connect(self._on_start)

        self._btn_stop = QPushButton("\u25A0  PARAR")
        self._btn_stop.setObjectName("btn_stop")
        self._btn_stop.setEnabled(False)
        self._btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_stop.clicked.connect(self._on_stop)

        self._btn_avatar = QPushButton("\u25C9  Avatar")
        self._btn_avatar.setObjectName("btn_secondary")
        self._btn_avatar.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_avatar.clicked.connect(self._toggle_avatar)

        self._btn_retry = QPushButton("\u21BA")
        self._btn_retry.setObjectName("btn_secondary")
        self._btn_retry.setToolTip("Reiniciar avatar (limpa cache e cookies)")
        self._btn_retry.setFixedWidth(48)
        self._btn_retry.setEnabled(False)
        self._btn_retry.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_retry.clicked.connect(self._retry_avatar)

        self._btn_clear = QPushButton("Limpar")
        self._btn_clear.setObjectName("btn_secondary")
        self._btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_clear.clicked.connect(self._terminal.clear)

        h.addWidget(self._btn_start)
        h.addWidget(self._btn_stop)
        h.addStretch()
        h.addWidget(self._btn_avatar)

        return w

    def _build_footer(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(2, 0, 2, 0)

        self._footer_label = QLabel("Pronto.")
        self._footer_label.setObjectName("footer")

        self._chunk_label = QLabel("")
        self._chunk_label.setObjectName("footer")

        h.addWidget(self._footer_label)
        h.addStretch()
        h.addWidget(self._chunk_label)
        return w

    # ---------------------------- Tema ----------------------------
    def apply_theme_colors(self, t: dict):
        self._ts_color = t["ts_color"]
        self._acc_color = t["accent"]
        self._txt_color = t["text"]
        self.btn_theme.setText("\u2600" if self._main._dark_mode else "\U0001F319")

    # ---------------------------- Blink ----------------------------
    def _setup_blink_timer(self):
        self._blink_state = False
        self._blink_timer = QTimer()
        self._blink_timer.setInterval(600)
        self._blink_timer.timeout.connect(self._blink_cursor)

    def _blink_cursor(self):
        if not self._is_running:
            return
        self._blink_state = not self._blink_state
        char = "\u2588" if self._blink_state else " "
        self._footer_label.setText(f"ouvindo {char}")

    # ---------------------------- Navegacao ----------------------------
    def _on_back(self):
        if self._is_running and self._worker:
            self._worker.stop()
        self.back_requested.emit()

    # ---------------------------- Fluxo ----------------------------
    def _get_model_name(self) -> str:
        return self._model_combo.currentText().split()[0].strip()

    def _on_start(self):
        model = self._get_model_name()
        self._log_system(f"iniciando modelo '{model}'... aguarde.")
        self._set_running(True, loading=True)

        self._worker = TranscriptionWorker(model_name=model)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.start_transcription)
        self._worker.text_received.connect(self._on_text)
        self._worker.started.connect(self._on_started)
        self._worker.glosa_received.connect(self._on_glosa)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(lambda: self._set_running(False))

        self._thread.start()

    def _on_started(self):
        self._set_running(True, loading=False)
        self._log_system("captura ativa — aguardando áudio.")

    def _on_stop(self):
        if self._worker:
            self._worker.stop()
        self._log_system("transcri\u00e7\u00e3o encerrada.")

    def _set_running(self, running: bool, loading: bool = False):
        self._is_running = running
        self._btn_start.setEnabled(not running)
        self._btn_stop.setEnabled(running)
        self._model_combo.setEnabled(not running)
        self._btn_back.setEnabled(not running)

        if running and loading:
            self._status_label.setObjectName("status_loading")
            self._status_label.setText("\u25D0  Carregando...")
        elif running:
            self._status_label.setObjectName("status_running")
            self._status_label.setText("\u25CF  Ao vivo")
            self._blink_timer.start()
        else:
            self._status_label.setObjectName("status_idle")
            self._status_label.setText("\u25CF  Ocioso")
            self._blink_timer.stop()
            self._footer_label.setText("Pronto.")

        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)

    def _toggle_avatar(self):
        from layers.avatar_window import AvatarWindow
        if self._avatar_window is None:
            self._avatar_window = AvatarWindow()
            self._avatar_window.show()
            self._btn_avatar.setText("\u25CE  Avatar")
            self._btn_retry.setEnabled(True)
            self._log_system("avatar iniciado \u2014 arraste para posicionar.")
        else:
            self._avatar_window.close()
            self._avatar_window = None
            self._btn_avatar.setText("\u25C9  Avatar")
            self._btn_retry.setEnabled(False)
            self._log_system("avatar fechado.")

    def _retry_avatar(self):
        if self._avatar_window:
            self._avatar_window.retry()
            self._log_system("avatar reiniciado \u2014 aguarde carregar...")

    def _on_glosa(self, glosa: str):
        if self._avatar_window:
            self._avatar_window.translate(glosa)

    def _on_text(self, text: str):
        # primeira transcricao recebida => sai do estado "carregando"
        if self._status_label.objectName() == "status_loading":
            self._set_running(True, loading=False)
        self._chunk_count += 1
        self._chunk_label.setText(f"{self._chunk_count} blocos")
        cursor = self._terminal.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        cursor.insertHtml(
            f'<span style="color:{self._ts_color};font-size:12px;">[{ts}]</span> '
            f'<span style="color:{self._acc_color};">\u25B8</span> '
            f'<span style="color:{self._txt_color};">{text}</span><br>'
        )
        self._terminal.setTextCursor(cursor)
        self._terminal.ensureCursorVisible()

    def _on_error(self, error: str):
        self._log_system(f"ERRO: {error}", color=self._main._theme["danger"])

    def _log_system(self, msg: str, color: str = None):
        if color is None:
            color = self._ts_color
        cursor = self._terminal.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(f'<span style="color:{color};font-size:12px;">// {msg}</span><br>')
        self._terminal.setTextCursor(cursor)
        self._terminal.ensureCursorVisible()

    def shutdown(self):
        if self._worker:
            self._worker.stop()
        if self._avatar_window:
            self._avatar_window.close()


# =====================================================================
#  TELA 3: Libras -> Audio  (camera -> texto -> voz)
# =====================================================================
class LibrasToAudioScreen(QWidget):
    back_requested = pyqtSignal()

    def __init__(self, main):
        super().__init__()
        self.setObjectName("root")
        self._main = main
        self._worker = None
        self._thread = None
        self._is_running = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(16)
        layout.addWidget(self._build_topbar())

        body = QHBoxLayout()
        body.setSpacing(16)

        # ---- Preview da camera ----
        self._camera_preview = QLabel(
            "\U0001F4F7\n\nA c\u00e2mera aparecer\u00e1 aqui.\n"
            "Pressione INICIAR para ativar."
        )
        self._camera_preview.setObjectName("camera_preview")
        self._camera_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._camera_preview.setMinimumSize(420, 320)
        body.addWidget(self._camera_preview, stretch=3)

        # ---- Painel de texto reconhecido ----
        right = QVBoxLayout()
        right.setSpacing(8)
        rh = QLabel("TEXTO RECONHECIDO")
        rh.setObjectName("recognized_header")
        self._recognized = QTextEdit()
        self._recognized.setObjectName("recognized")
        self._recognized.setReadOnly(True)
        self._recognized.setPlaceholderText(
            "// o texto interpretado dos sinais aparecer\u00e1 aqui\n"
            "// e ser\u00e1 reproduzido em voz"
        )
        right.addWidget(rh)
        right.addWidget(self._recognized, stretch=1)
        body.addLayout(right, stretch=2)

        layout.addLayout(body, stretch=1)
        layout.addWidget(self._build_controls())

        # aviso de acessibilidade / status de integracao
        note = QLabel(
            "\u2139  Reconhecimento de sinais em integra\u00e7\u00e3o. A c\u00e2mera "
            "e a leitura em voz j\u00e1 est\u00e3o ativas."
        )
        note.setObjectName("footer")
        note.setWordWrap(True)
        layout.addWidget(note)

    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("topbar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(0, 0, 0, 12)

        self._btn_back = QPushButton("\u2190  Voltar")
        self._btn_back.setObjectName("btn_back")
        self._btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_back.clicked.connect(self._on_back)

        title = QLabel("\U0001F91F  Libras \u2192 \u00C1udio")
        title.setObjectName("screen_title")

        self._status_label = QLabel("\u25CF  Ocioso")
        self._status_label.setObjectName("status_idle")

        self.btn_theme = QPushButton("\u2600")
        self.btn_theme.setObjectName("btn_theme")
        self.btn_theme.setToolTip("Alternar tema claro/escuro")
        self.btn_theme.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_theme.clicked.connect(self._main._toggle_theme)

        h.addWidget(self._btn_back)
        h.addSpacing(14)
        h.addWidget(title)
        h.addStretch()
        h.addWidget(self._status_label)
        h.addSpacing(10)
        h.addWidget(self.btn_theme)
        return bar

    def _build_controls(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)

        self._btn_start = QPushButton("\u25B6  INICIAR")
        self._btn_start.setObjectName("btn_start")
        self._btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_start.clicked.connect(self._on_start)

        self._btn_stop = QPushButton("\u25A0  PARAR")
        self._btn_stop.setObjectName("btn_stop")
        self._btn_stop.setEnabled(False)
        self._btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_stop.clicked.connect(self._on_stop)

        self._btn_clear = QPushButton("Limpar")
        self._btn_clear.setObjectName("btn_secondary")
        self._btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_clear.clicked.connect(self._recognized.clear)

        h.addWidget(self._btn_start)
        h.addWidget(self._btn_stop)
        h.addStretch()
        h.addWidget(self._btn_clear)
        return w

    # ---------------------------- Tema ----------------------------
    def apply_theme_colors(self, t: dict):
        self.btn_theme.setText("\u2600" if self._main._dark_mode else "\U0001F319")

    # ---------------------------- Navegacao ----------------------------
    def _on_back(self):
        if self._is_running and self._worker:
            self._worker.stop()
        self.back_requested.emit()

    # ---------------------------- Fluxo ----------------------------
    def _on_start(self):
        self._set_running(True, loading=True)
        self._worker = CameraWorker()
        self._thread = QThread()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.start_capture)
        self._worker.frame_ready.connect(self._on_frame)
        self._worker.text_recognized.connect(self._on_recognized)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(lambda: self._set_running(False))
        self._thread.start()

    def _on_stop(self):
        if self._worker:
            self._worker.stop()

    def _set_running(self, running: bool, loading: bool = False):
        self._is_running = running
        self._btn_start.setEnabled(not running)
        self._btn_stop.setEnabled(running)
        self._btn_back.setEnabled(not running)

        if running and loading:
            self._status_label.setObjectName("status_loading")
            self._status_label.setText("\u25D0  Abrindo c\u00e2mera...")
        elif running:
            self._status_label.setObjectName("status_running")
            self._status_label.setText("\u25CF  Ao vivo")
        else:
            self._status_label.setObjectName("status_idle")
            self._status_label.setText("\u25CF  Ocioso")
            self._camera_preview.setText(
                "\U0001F4F7\n\nA c\u00e2mera aparecer\u00e1 aqui.\n"
                "Pressione INICIAR para ativar."
            )
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)

    def _on_frame(self, image: QImage):
        if self._status_label.objectName() == "status_loading":
            self._set_running(True, loading=False)
        pix = QPixmap.fromImage(image).scaled(
            self._camera_preview.width(), self._camera_preview.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._camera_preview.setPixmap(pix)

    def _on_recognized(self, text: str):
        cursor = self._recognized.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        cursor.insertHtml(
            f'<span style="color:{self._main._theme["text_dim"]};font-size:12px;">[{ts}]</span> '
            f'<span style="color:{self._main._theme["text"]};">{text}</span><br>'
        )
        self._recognized.setTextCursor(cursor)
        self._recognized.ensureCursorVisible()
        speak(text)

    def _on_error(self, error: str):
        self._camera_preview.setText(f"\u26A0\n\n{error}")

    def shutdown(self):
        if self._worker:
            self._worker.stop()


# =====================================================================
#  JANELA PRINCIPAL  (navegacao + tema global)
# =====================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LIBRAS MIDDLEWARE")
        self.setMinimumSize(880, 640)
        self.resize(980, 720)
        self._dark_mode = True
        self._theme = DARK

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self.welcome = WelcomeScreen(self)
        self.audio2libras = AudioToLibrasScreen(self)
        self.libras2audio = LibrasToAudioScreen(self)

        self._stack.addWidget(self.welcome)        # index 0
        self._stack.addWidget(self.audio2libras)   # index 1
        self._stack.addWidget(self.libras2audio)   # index 2

        # navegacao
        self.welcome.mode_selected.connect(self._go_to_mode)
        self.audio2libras.back_requested.connect(self._go_home)
        self.libras2audio.back_requested.connect(self._go_home)

        self._screens = [self.welcome, self.audio2libras, self.libras2audio]
        self._apply_theme()

    # ---------------------------- Navegacao ----------------------------
    def _go_to_mode(self, mode: str):
        if mode == "audio2libras":
            self._stack.setCurrentWidget(self.audio2libras)
        elif mode == "libras2audio":
            self._stack.setCurrentWidget(self.libras2audio)

    def _go_home(self):
        self._stack.setCurrentWidget(self.welcome)

    # ---------------------------- Tema ----------------------------
    def _toggle_theme(self):
        self._dark_mode = not self._dark_mode
        self._apply_theme()

    def _apply_theme(self):
        self._theme = DARK if self._dark_mode else LIGHT
        QApplication.instance().setStyleSheet(build_stylesheet(self._theme))
        for screen in self._screens:
            screen.apply_theme_colors(self._theme)

    # ---------------------------- Encerramento ----------------------------
    def closeEvent(self, event):
        self.audio2libras.shutdown()
        self.libras2audio.shutdown()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
