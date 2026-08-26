import sys
import os
import tempfile
import threading
import http.server
import socketserver
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QHBoxLayout
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage, QWebEngineProfile
from PyQt6.QtCore import Qt, QUrl, QPoint, pyqtSlot, QTimer, QCoreApplication
from PyQt6.QtGui import QFont

HTTP_PORT = 19825

HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body {
  width: 100%; height: 100%;
  background: #1a2a3a;
  overflow: hidden;
}
[vw-access-button] { display: none !important; }
[vw-plugin-wrapper] { position: fixed !important; inset: 0 !important; }
.vw-plugin-top-wrapper { width: 100% !important; height: 100% !important; }

#gameContainer {
  position: fixed !important;
  inset: 0 !important;
  width: 100% !important;
  height: 100% !important;
}
#gameContainer canvas {
  position: absolute !important;
  top: 0 !important;
  left: 50% !important;
  transform: translateX(-50%) !important;
  height: 100% !important;
  width: auto !important;
  min-width: 150% !important;
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
console.log("[VLibras] Página carregada");

new window.VLibras.Widget({
  rootPath: 'https://vlibras.gov.br/app',
  avatar: 'icaro',
  opacity: 0,
  position: 'BR',
});

let playerReady = false;
let translateQueue = [];

function log(msg) {
  console.log("[VLibras JS] " + msg);
}

// Tenta inicializar o player
function initPlayer() {
  log("Tentando inicializar...");
  var btn = document.querySelector('[vw-access-button]');
  if (btn) {
    btn.click();
    log("Botão de acesso clicado");

    setTimeout(() => {
      var denyBtn = document.querySelector('.vpw-guide__main__deny-btn');
      if (denyBtn) {
        denyBtn.click();
        log("Tutorial fechado");
      }
    }, 1000);
  } else {
    setTimeout(initPlayer, 600);
  }
}
setTimeout(initPlayer, 1200);

// Verifica se o player está pronto
function checkPlayerReady() {
  if (document.querySelector('#gameContainer canvas')) {
    playerReady = true;
    log("Player VLibras pronto!");
    processQueue();
  } else {
    setTimeout(checkPlayerReady, 800);
  }
}
setTimeout(checkPlayerReady, 3000);

// Processa fila de traduções
function processQueue() {
  if (translateQueue.length === 0 || !playerReady) return;

  const text = translateQueue.shift();
  log("Traduzindo: " + text);

  try {
    // Estratégia 1: Campo de texto + botão (mais confiável)
    const textarea = document.querySelector('.vp-user-textarea');
    const playBtn = document.querySelector('.vp-play-gloss-button');

    if (textarea && playBtn) {
      textarea.value = text;
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
      setTimeout(() => {
        playBtn.removeAttribute('disabled');
        playBtn.click();
        log("Tradução enviada via botão");
      }, 200);
    } 
    // Estratégia 2: API interna
    else if (window.vlibras && window.vlibras.translate) {
      window.vlibras.translate(text);
      log("Usando window.vlibras.translate");
    } 
    // Estratégia 3: Evento customizado
    else {
      window.dispatchEvent(new CustomEvent('vlibras:translate', { 
        detail: { text: text } 
      }));
    }
  } catch (e) {
    log("Erro ao traduzir: " + e);
  }

  // Processa próximo após um delay baseado no tamanho do texto
  const delay = Math.max(2000, text.split(' ').length * 600);
  setTimeout(processQueue, delay);
}

// Função global chamada pelo Python
window.traduzir = function(text) {
  if (text && text.trim()) {
    translateQueue.push(text.trim());
    log("Texto adicionado na fila: " + text);
    if (playerReady) processQueue();
  }
};

log("Script VLibras carregado com sucesso");
</script>
</body>
</html>"""

# ====================== Servidor ======================
_server_started = False


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML.encode("utf-8"))

    def log_message(self, *args): pass


def start_http_server():
    global _server_started
    if _server_started: return
    _server_started = True

    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    def run_server():
        try:
            with ReusableTCPServer(("127.0.0.1", HTTP_PORT), Handler) as httpd:
                print(f"[Avatar] Servidor HTTP iniciado na porta {HTTP_PORT}")
                httpd.serve_forever()
        except Exception as e:
            print(f"[Avatar] Servidor: {e}")

    threading.Thread(target=run_server, daemon=True).start()


# ====================== AvatarWindow ======================
class ConsolePage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        print(f"[JS] {message}")


class AvatarWindow(QWidget):
    def __init__(self, width=360, height=520):
        super().__init__()
        self._drag_pos = QPoint()
        self._width = width
        self._height = height

        start_http_server()
        self._setup_window()
        self._setup_ui()

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setStyleSheet("background: #1a2a3a;")
        self.resize(self._width, self._height)
        self._place_on_screen()

    def _place_on_screen(self):
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - self._width - 30, screen.height() - self._height - 100)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Avatar
        cache_path = os.path.join(tempfile.gettempdir(), "vlibras_wgt")
        os.makedirs(cache_path, exist_ok=True)

        self._profile = QWebEngineProfile("vlibras_wgt", self)
        self._profile.setCachePath(cache_path)
        self._profile.setPersistentStoragePath(cache_path)

        self._page = ConsolePage(self._profile, self)
        settings = self._page.settings()
        for attr in (QWebEngineSettings.WebAttribute.JavascriptEnabled,
                     QWebEngineSettings.WebAttribute.PluginsEnabled,
                     QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls):
            settings.setAttribute(attr, True)

        self._webview = QWebEngineView()
        self._webview.setPage(self._page)
        self._webview.load(QUrl(f"http://127.0.0.1:{HTTP_PORT}/"))
        layout.addWidget(self._webview, stretch=1)

        # Legenda
        sub_container = QWidget()
        sub_container.setStyleSheet("background: rgba(0,0,0,0.9); border-top: 2px solid #00FF88;")
        sub_layout = QHBoxLayout(sub_container)
        sub_layout.setContentsMargins(16, 12, 16, 12)

        self._subtitle = QLabel("Aguardando tradução...")
        self._subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle.setWordWrap(True)
        self._subtitle.setFont(QFont("Consolas", 11, QFont.Weight.Medium))
        self._subtitle.setStyleSheet("color: #00FFAA;")
        sub_layout.addWidget(self._subtitle)

        layout.addWidget(sub_container)

    @pyqtSlot(str)
    def translate(self, text: str):
        if not text or not text.strip():
            return

        clean_text = text.strip()
        self._subtitle.setText(clean_text)
        print(f"[Avatar] Enviando para tradução: {clean_text}")

        escaped = clean_text.replace("'", "\\'").replace('"', '\\"')
        self._page.runJavaScript(f"traduzir('{escaped}');")

    def retry(self):
        print("[Avatar] Reiniciando avatar...")
        self._profile.cookieStore().deleteAllCookies()
        self._webview.load(QUrl(f"http://127.0.0.1:{HTTP_PORT}/"))
        self._subtitle.setText("Reiniciando...")

    # Drag
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and not self._drag_pos.isNull():
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = QPoint()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--enable-gpu --ignore-gpu-blocklist"

    avatar = AvatarWindow()
    avatar.show()

    # Teste automático
    QTimer.singleShot(7000, lambda: avatar.translate("OLÁ, TESTANDO A TRADUÇÃO DO AVATAR"))

    sys.exit(app.exec())