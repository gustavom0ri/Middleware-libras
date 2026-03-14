"""
Camada 4 — Avatar VLibras flutuante
Janela sem borda, transparente, sempre no topo, arrastável.
Embute o player oficial do VLibras via QWebEngineView.
"""

import sys
import os
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtCore import Qt, QUrl, QPoint, pyqtSlot
from PyQt6.QtGui import QColor
import tempfile

# HTML que embute o player VLibras com fundo transparente
VLIBRAS_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body {
    background: transparent !important;
    overflow: hidden;
    width: 100%;
    height: 100%;
  }
  /* Esconde todos os controles do widget VLibras — só o avatar */
  [vw-access-button],
  .vw-plugin-top-wrapper,
  .vw-settings,
  .vw-footer,
  .vw-text-bar,
  .vw-progress-bar {
    display: none !important;
  }
  [vw-plugin-wrapper] {
    position: fixed !important;
    bottom: 0 !important;
    left: 0 !important;
    width: 100% !important;
    height: 100% !important;
    background: transparent !important;
  }
  /* Canvas do Unity (avatar 3D) */
  canvas {
    background: transparent !important;
  }
</style>
</head>
<body>
  <div vw class="enabled">
    <div vw-access-button class="active"></div>
    <div vw-plugin-wrapper>
      <div class="vw-plugin-top-wrapper"></div>
    </div>
  </div>
  <script src="https://vlibras.gov.br/app/vlibras-plugin.js"></script>
  <script>
    // Inicializa o widget em modo ativo
    new window.VLibras.Widget({
      rootPath: 'https://vlibras.gov.br/app',
      personalization: 'https://vlibras.gov.br/config/configs.json',
      opacity: 0,        // fundo do widget transparente
      avatar: 'icaro',   // icaro | hosana | guga | random
    });

    // Abre automaticamente o player ao carregar
    window.addEventListener('load', () => {
      setTimeout(() => {
        const btn = document.querySelector('[vw-access-button]');
        if (btn) btn.click();
      }, 1500);
    });

    // Função chamada pelo Python para traduzir uma glosa
    function traduzir(glosa) {
      if (window.VLibras && window.VLibras.Widget) {
        window.dispatchEvent(new CustomEvent('vlibras:translate', {
          detail: { text: glosa }
        }));
      }
    }
  </script>
</body>
</html>
"""


class AvatarWindow(QWidget):
    """
    Janela flutuante transparente com o avatar VLibras.
    - Sem borda e sem barra de título
    - Sempre visível sobre outras janelas
    - Arrastável pelo mouse
    - Redimensionável pelos cantos
    """

    def __init__(self, width: int = 320, height: int = 420):
        super().__init__()
        self._drag_pos = QPoint()
        self._setup_window(width, height)
        self._setup_webview()

    # ------------------------------------------------------------------
    # Configuração da janela
    # ------------------------------------------------------------------
    def _setup_window(self, width: int, height: int):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint      # sem borda
            | Qt.WindowType.WindowStaysOnTopHint   # sempre no topo
            | Qt.WindowType.Tool                   # não aparece na taskbar
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)  # fundo transparente
        self.resize(width, height)

        # Posiciona no canto inferior direito da tela
        screen = QApplication.primaryScreen().geometry()
        self.move(
            screen.width() - width - 20,
            screen.height() - height - 60,
        )

    def _setup_webview(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._webview = QWebEngineView()
        self._webview.setStyleSheet("background: transparent;")
        self._webview.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Habilita JavaScript e plugins necessários
        settings = self._webview.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)

        # Carrega o HTML do player VLibras
        self._webview.setHtml(VLIBRAS_HTML, QUrl("https://vlibras.gov.br"))

        layout.addWidget(self._webview)

    # ------------------------------------------------------------------
    # Tradução — chamado pela interface principal
    # ------------------------------------------------------------------
    @pyqtSlot(str)
    def translate(self, glosa: str):
        """Envia uma glosa para o avatar animar."""
        # Escapa aspas para não quebrar o JavaScript
        glosa_escaped = glosa.replace("'", "\\'").replace('"', '\\"')
        self._webview.page().runJavaScript(f"traduzir('{glosa_escaped}');")

    # ------------------------------------------------------------------
    # Arrastar a janela pelo mouse
    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and not self._drag_pos.isNull():
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = QPoint()


# ------------------------------------------------------------------
# Teste isolado da janela do avatar
# ------------------------------------------------------------------
if __name__ == "__main__":
    # Fix DLL torch no Windows
    try:
        import torch
        torch_dir = os.path.join(os.path.dirname(torch.__file__), "lib")
        if os.path.isdir(torch_dir):
            os.add_dll_directory(torch_dir)
    except Exception:
        pass

    app = QApplication(sys.argv)

    avatar = AvatarWindow()
    avatar.show()

    # Testa tradução após 3 segundos
    from PyQt6.QtCore import QTimer
    QTimer.singleShot(3000, lambda: avatar.translate("OLÁ TUDO BEM VOCÊ"))

    sys.exit(app.exec())