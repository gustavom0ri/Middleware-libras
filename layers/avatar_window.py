import sys
import os
import tempfile
import threading
import http.server
import socketserver
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage, QWebEngineProfile
from PyQt6.QtCore import Qt, QUrl, QPoint, pyqtSlot, QTimer

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
/* Esconde tudo exceto o player */
[vw-access-button] { display: none !important; }
[vw-plugin-wrapper] {
  position: fixed !important;
  inset: 0 !important;
  z-index: 1 !important;
}
.vw-plugin-top-wrapper {
  width: 100% !important;
  height: 100% !important;
}
/* Esconde controles internos do player pelos seletores exatos */
[vp-main-guide-screen],
[vp-rate-box],
[vp-suggestion-screen],
[vp-settings],
[vp-info-screen],
[vp-translator-screen],
[vp-more-options-screen],
[vp-aux-controls],
[vp-controls],
[vp-change-avatar],
[vp-emotions-tooltip],
[vp-click-blocker],
.vp-guide-container,
.vpw-controls,
.vpw-message-box,
[settings-btn],
[settings-btn-close],
.vpw-settings-btn,
.vpw-mes {
  display: none !important;
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
new window.VLibras.Widget({
  rootPath: 'https://vlibras.gov.br/app',
  avatar: 'icaro',
  opacity: 0,
  position: 'BR',
});

// Abre o player e fecha tutorial automaticamente
function init() {
  var btn = document.querySelector('[vw-access-button]');
  if (btn) {
    btn.click();

    setTimeout(function() {
      var denyBtn = document.querySelector('.vpw-guide__main__deny-btn');
      if (denyBtn) denyBtn.click();

      var hideSelectors = [
        '[vp-main-guide-screen]','[vp-rate-box]','[vp-suggestion-screen]',
        '[vp-settings]','[vp-info-screen]','[vp-translator-screen]',
        '[vp-more-options-screen]','[vp-aux-controls]','[vp-controls]',
        '[vp-change-avatar]','[vp-click-blocker]','[vp-emotions-tooltip]',
        '.vp-guide-container','.vpw-controls','.vpw-message-box',
        '[settings-btn]','.vpw-settings-btn','.vpw-mes'
      ];
      hideSelectors.forEach(function(sel) {
        document.querySelectorAll(sel).forEach(function(el) { el.style.display = 'none'; });
      });
    }, 800);

    setInterval(function() {
      var denyBtn = document.querySelector('.vpw-guide__main__deny-btn');
      if (denyBtn && denyBtn.offsetParent !== null) denyBtn.click();

      var hideSelectors = [
        '[vp-main-guide-screen]','[vp-rate-box]','[vp-suggestion-screen]',
        '[vp-controls]','[vp-aux-controls]','[vp-change-avatar]',
        '.vp-guide-container','.vpw-controls','.vpw-message-box'
      ];
      hideSelectors.forEach(function(sel) {
        document.querySelectorAll(sel).forEach(function(el) { el.style.display = 'none'; });
      });
    }, 1500);

  } else {
    setTimeout(init, 500);
  }
}
setTimeout(init, 2000);

// Funcao para traduzir texto
function traduzir(texto) {
  window.dispatchEvent(new CustomEvent('vlibras:translate', {
    detail: { text: texto }
  }));
}
</script>
</body>
</html>"""


_server_started = False

def start_server():
    global _server_started
    if _server_started:
        return
    _server_started = True

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(HTML.encode("utf-8"))
        def log_message(self, *a): pass

    try:
        with socketserver.TCPServer(("127.0.0.1", HTTP_PORT), Handler) as srv:
            srv.serve_forever()
    except OSError:
        pass

threading.Thread(target=start_server, daemon=True).start()


class ConsolePage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        print(f"[JS] {message}")


class AvatarWindow(QWidget):
    def __init__(self, width=300, height=420):
        super().__init__()
        self._drag_pos = QPoint()
        self._width = width
        self._height = height
        self._setup_window()
        self._setup_webview()

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setStyleSheet("background: #1a2a3a;")
        self.resize(self._width, self._height)
        self._place_on_screen()

    def _place_on_screen(self):
        screen = QApplication.primaryScreen().geometry()
        self.move(
            screen.width()  - self._width  - 20,
            screen.height() - self._height - 60,
        )

    def _setup_webview(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        cache_path = os.path.join(tempfile.gettempdir(), "vlibras_wgt")
        os.makedirs(cache_path, exist_ok=True)

        self._profile = QWebEngineProfile("vlibras_wgt", self)
        self._profile.setCachePath(cache_path)
        self._profile.setPersistentStoragePath(cache_path)

        self._page = ConsolePage(self._profile, self)

        settings = self._page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)

        self._webview = QWebEngineView()
        self._webview.setPage(self._page)
        self._webview.setStyleSheet("background: #1a2a3a;")
        self._webview.load(QUrl(f"http://127.0.0.1:{HTTP_PORT}/"))
        layout.addWidget(self._webview)

    def retry(self):
        self._profile.cookieStore().deleteAllCookies()
        self._place_on_screen()
        self._webview.load(QUrl(f"http://127.0.0.1:{HTTP_PORT}/"))

    @pyqtSlot(str)
    def translate(self, text: str):
        escaped = text.replace("'", "\\'").replace('"', '\\"')
        self._page.runJavaScript(f"traduzir('{escaped}');")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and not self._drag_pos.isNull():
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = QPoint()


if __name__ == "__main__":
    try:
        import torch
        torch_dir = os.path.join(os.path.dirname(torch.__file__), "lib")
        if os.path.isdir(torch_dir):
            os.add_dll_directory(torch_dir)
    except Exception:
        pass

    from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa
    from PyQt6.QtCore import QCoreApplication
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--enable-gpu --ignore-gpu-blocklist"

    app = QApplication(sys.argv)
    avatar = AvatarWindow()
    avatar.show()
    QTimer.singleShot(10000, lambda: avatar.translate("OLA TUDO BEM"))
    sys.exit(app.exec())