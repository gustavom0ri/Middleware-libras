# -*- coding: utf-8 -*-
"""
avatar_extras.py  (v3 — captura a instancia via prototype)
==========================================================
Velocidade + troca de avatar + reiniciar, SEM alterar main.py nem
avatar_window.py.

O PROBLEMA RESOLVIDO NESTA VERSAO
---------------------------------
Os logs mostraram:

    Globais novas: onLoadPlayer, updateProgress, onPlayingStateChange,
                   CounterGloss, GetAvatar, FinishWelcome, VLibras

`player` NAO esta ali: a instancia vive dentro de um closure do script do
avatar_window.py, entao `typeof player` falha (o proprio codigo dele
tambem loga "applySpeed -> sem API" pelo mesmo motivo).

SOLUCAO
    O CONSTRUTOR (window.VLibras.Player) e global. Envolvemos os metodos
    do seu PROTOTYPE: assim que qualquer metodo e chamado na instancia,
    capturamos `this` em window.__vlPlayer. Como o app chama translate()
    a cada transcricao, a instancia e capturada naturalmente.
    Alem disso, varremos o window em busca de um objeto que seja
    `instanceof VLibras.Player` — costuma achar de imediato.

Se a instancia ainda nao foi capturada, a preferencia fica PENDENTE e e
aplicada automaticamente assim que ela aparecer.

USO NO main.py (1 linha, ja feito)
    from Layers.avatar_extras import instalar_controles
    instalar_controles(self, self._avatar_window)
"""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QSlider, QComboBox, QPushButton
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtCore import Qt, QUrl, QTimer


AVATARES = [("Ícaro", "icaro"), ("Hosana", "hosana"), ("Guga", "guga")]
SPEED_MIN, SPEED_MAX, SPEED_DEFAULT = 5, 30, 20      # decimos (20 = 2.0x)


# ===========================================================================
# JS: captura a instancia do player e expoe setSpeed/setAvatar
# ===========================================================================
JS_API = r"""
(function () {
  function L(m) { console.log("[VLibras JS] " + m); }

  if (window.__vlExtras) { window.__vlFind(); return "ja-instalado"; }
  window.__vlExtras = true;

  window.__vlPlayer  = window.__vlPlayer  || null;
  window.__vlSpeed   = window.__vlSpeed   || 2;
  window.__vlAvatar  = window.__vlAvatar  || 'icaro';
  window.__vlPending = window.__vlPending || {};

  // ---------------------------------------------------------------
  // 1) Envolve o PROTOTYPE para capturar `this` na proxima chamada.
  //    O construtor e global (window.VLibras.Player), a instancia nao.
  // ---------------------------------------------------------------
  function wrapPrototype() {
    try {
      var Ctor = window.VLibras && window.VLibras.Player;
      if (!Ctor || !Ctor.prototype || Ctor.prototype.__vlWrapped) return false;
      var proto = Ctor.prototype;
      proto.__vlWrapped = true;

      Object.getOwnPropertyNames(proto).forEach(function (k) {
        if (k === 'constructor' || k === '__vlWrapped') return;
        var fn;
        try { fn = proto[k]; } catch (e) { return; }
        if (typeof fn !== 'function') return;
        proto[k] = function () {
          if (!window.__vlPlayer) {
            window.__vlPlayer = this;
            L("Instancia do player capturada via ." + k + "()");
            window.__vlFlush();
          }
          return fn.apply(this, arguments);
        };
      });
      L("Prototype do player envolvido.");
      return true;
    } catch (e) { L("wrapPrototype erro: " + e); return false; }
  }

  // ---------------------------------------------------------------
  // 2) Varre o window procurando um objeto instanceof VLibras.Player
  // ---------------------------------------------------------------
  window.__vlFind = function () {
    if (window.__vlPlayer) return window.__vlPlayer;
    var Ctor = window.VLibras && window.VLibras.Player;
    if (!Ctor) return null;

    function scan(obj, depth, seen) {
      if (!obj || depth > 3) return null;
      for (var k in obj) {
        var v;
        try { v = obj[k]; } catch (e) { continue; }
        if (!v || typeof v !== 'object') continue;
        try { if (v instanceof Ctor) return v; } catch (e) {}
        if (typeof v.setSpeed === 'function' &&
            typeof v.changeAvatar === 'function') return v;
        if (depth < 3 && seen.indexOf(v) === -1) {
          seen.push(v);
          var r = scan(v, depth + 1, seen);
          if (r) return r;
        }
      }
      return null;
    }

    var found = null;
    try { found = scan(window, 0, []); } catch (e) {}
    if (found) {
      window.__vlPlayer = found;
      L("Instancia do player encontrada por varredura.");
      window.__vlFlush();
    }
    return found;
  };

  // ---------------------------------------------------------------
  // 3) Aplica preferencias pendentes assim que a instancia aparece
  // ---------------------------------------------------------------
  window.__vlFlush = function () {
    var p = window.__vlPlayer;
    if (!p) return;
    if (window.__vlPending.speed != null) {
      try { p.setSpeed(window.__vlPending.speed);
            L("Velocidade pendente aplicada: " + window.__vlPending.speed + "x");
      } catch (e) {}
      window.__vlPending.speed = null;
    }
    if (window.__vlPending.avatar) {
      try { p.changeAvatar(window.__vlPending.avatar);
            L("Avatar pendente aplicado: " + window.__vlPending.avatar);
      } catch (e) {}
      window.__vlPending.avatar = null;
    }
  };

  // ---------------------------------------------------------------
  // API publica
  // ---------------------------------------------------------------
  window.setSpeed = function (v) {
    var s = parseFloat(v);
    if (!s || s <= 0) return "invalido";
    window.__vlSpeed = s;
    var p = window.__vlPlayer || window.__vlFind();
    if (p && typeof p.setSpeed === 'function') {
      try { p.setSpeed(s); L("setSpeed(" + s + ") OK"); return "ok"; }
      catch (e) { L("setSpeed erro: " + e); return "erro"; }
    }
    window.__vlPending.speed = s;
    L("setSpeed(" + s + ") PENDENTE (instancia ainda nao capturada)");
    return "pendente";
  };

  window.setAvatar = function (name) {
    if (!name) return "vazio";
    name = String(name).toLowerCase();
    window.__vlAvatar = name;
    var p = window.__vlPlayer || window.__vlFind();
    if (p && typeof p.changeAvatar === 'function') {
      try {
        p.changeAvatar(name);
        L("changeAvatar(" + name + ") OK");
        // Trocar de avatar reseta a velocidade -> reaplica.
        setTimeout(function () { window.setSpeed(window.__vlSpeed); }, 2500);
        return "ok";
      } catch (e) { L("changeAvatar erro: " + e); return "erro"; }
    }
    window.__vlPending.avatar = name;
    L("setAvatar(" + name + ") PENDENTE");
    return "pendente";
  };

  // Reaplica a velocidade a cada traducao (o player volta para 1x sozinho)
  if (!window.__vlWrapTraduzir && typeof window.traduzir === 'function') {
    window.__vlWrapTraduzir = true;
    var _orig = window.traduzir;
    window.traduzir = function () {
      try { window.setSpeed(window.__vlSpeed); } catch (e) {}
      return _orig.apply(this, arguments);
    };
  }

  wrapPrototype();
  window.__vlFind();

  // Novas tentativas de captura (o player pode demorar a instanciar)
  var tries = 0;
  var iv = setInterval(function () {
    tries++;
    if (window.__vlPlayer || tries > 40) { clearInterval(iv); return; }
    wrapPrototype();
    window.__vlFind();
  }, 1500);

  return "instalado";
})();
"""


# ===========================================================================
# PATCH do AvatarWindow
# ===========================================================================
def patch_avatar(avatar):
    avatar._speed = 2.0
    avatar._avatar_name = "icaro"

    def _run(js_extra="", cb=None):
        js = JS_API + ("\n" + js_extra if js_extra else "")
        if cb:
            avatar._page.runJavaScript(js, cb)
        else:
            avatar._page.runJavaScript(js)

    def set_speed(speed):
        try:
            speed = max(0.5, min(3.0, float(speed)))
        except (TypeError, ValueError):
            return
        avatar._speed = speed
        print(f"[Avatar] Velocidade -> {speed}x")
        _run(f"window.setSpeed({speed});")

    def set_avatar(name):
        name = str(name or "").strip().lower()
        if name not in ("icaro", "hosana", "guga"):
            return
        avatar._avatar_name = name
        print(f"[Avatar] Avatar -> {name}")
        _run(f"window.setAvatar('{name}');")

    def reload_avatar():
        """
        Reinicia SEM tela branca.

        O Unity WebGL nao libera o contexto grafico num reload: a instancia
        antiga segura o canvas e a nova nunca renderiza. Por isso destruimos
        a QWebEngineView/QWebEnginePage e criamos novas.
        """
        print("[Avatar] Reiniciando (recriando a WebView)...")
        try:
            avatar._subtitle.setText("Reiniciando avatar...")
        except Exception:
            pass

        try:
            avatar._page.runJavaScript(
                "try{var u=(window.gameInstance||window.unityInstance);"
                "if(u&&u.Quit)u.Quit();}catch(e){}")
        except Exception:
            pass

        layout = avatar.layout()
        old_view, old_page = avatar._webview, avatar._page
        try:
            layout.removeWidget(old_view)
            old_view.setParent(None)
            old_view.deleteLater()
            old_page.deleteLater()
        except Exception:
            pass

        ConsolePage = type(old_page)
        avatar._page = ConsolePage(avatar._profile, avatar,
                                   caption_cb=avatar._update_caption)
        s = avatar._page.settings()
        for attr in (QWebEngineSettings.WebAttribute.JavascriptEnabled,
                     QWebEngineSettings.WebAttribute.PluginsEnabled,
                     QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
                     QWebEngineSettings.WebAttribute.WebGLEnabled,
                     QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled):
            try:
                s.setAttribute(attr, True)
            except Exception:
                pass

        avatar._webview = QWebEngineView()
        avatar._webview.setPage(avatar._page)
        avatar._webview.load(QUrl(avatar._base_url))
        layout.insertWidget(0, avatar._webview, stretch=1)

        # Reinstala a API e restaura as preferencias.
        QTimer.singleShot(6000, lambda: _run(
            f"window.setSpeed({avatar._speed});"
            + (f"window.setAvatar('{avatar._avatar_name}');"
               if avatar._avatar_name != "icaro" else "")))

    avatar.set_speed = set_speed
    avatar.set_avatar = set_avatar
    avatar.reload_avatar = reload_avatar
    avatar.retry = reload_avatar

    # Instala cedo e reinstala algumas vezes (o player demora a instanciar).
    for atraso in (4000, 9000, 15000):
        QTimer.singleShot(atraso, lambda: _run())
    return avatar


# ===========================================================================
# PAINEL DE CONTROLES
# ===========================================================================
class AvatarControls(QWidget):
    """VELOCIDADE [slider] 2.0x | AVATAR [combo] | ↻ Reiniciar"""

    def __init__(self, avatar_window, parent=None):
        super().__init__(parent)
        self._avatar = avatar_window

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(14)

        lbl = QLabel("VELOCIDADE")
        lbl.setObjectName("config_label")
        root.addWidget(lbl)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(SPEED_MIN)
        self.slider.setMaximum(SPEED_MAX)
        self.slider.setValue(SPEED_DEFAULT)
        self.slider.setTickInterval(5)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider.setMinimumWidth(150)
        self.slider.valueChanged.connect(self._on_speed)
        root.addWidget(self.slider)

        self.lbl_speed = QLabel("2.0x")
        self.lbl_speed.setObjectName("config_label")
        self.lbl_speed.setMinimumWidth(42)
        self.lbl_speed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.lbl_speed)

        lbl2 = QLabel("AVATAR")
        lbl2.setObjectName("config_label")
        root.addWidget(lbl2)

        self.combo = QComboBox()
        self.combo.setStyleSheet("QComboBox { min-width: 120px; }")
        for nome, valor in AVATARES:
            self.combo.addItem(nome, valor)
        self.combo.currentIndexChanged.connect(self._on_avatar)
        root.addWidget(self.combo)

        self.btn_reload = QPushButton("↻ Reiniciar")
        self.btn_reload.setObjectName("btn_secondary")
        self.btn_reload.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reload.clicked.connect(self._on_reload)
        root.addWidget(self.btn_reload)

        root.addStretch(1)

    def _on_speed(self, value):
        speed = value / 10.0
        self.lbl_speed.setText(f"{speed:.1f}x")
        if hasattr(self._avatar, "set_speed"):
            self._avatar.set_speed(speed)

    def _on_avatar(self, index):
        if hasattr(self._avatar, "set_avatar"):
            self._avatar.set_avatar(self.combo.itemData(index))

    def _on_reload(self):
        if hasattr(self._avatar, "reload_avatar"):
            self._avatar.reload_avatar()
        elif hasattr(self._avatar, "retry"):
            self._avatar.retry()


# ===========================================================================
# INSTALACAO AUTOMATICA
# ===========================================================================
def instalar_controles(main_window, avatar, container_name="config_panel"):
    patch_avatar(avatar)
    controls = AvatarControls(avatar)

    alvo = main_window.findChild(QWidget, container_name)
    if alvo is None:
        for w in main_window.findChildren(QWidget):
            nome = (w.objectName() or "").lower()
            if "config" in nome or "panel" in nome:
                alvo = w
                break
    if alvo is None:
        alvo = main_window.centralWidget()

    if alvo is not None and alvo.layout() is not None:
        alvo.layout().addWidget(controls)
        print(f"[Avatar] Controles instalados em '{alvo.objectName()}'.")
    else:
        controls.setWindowTitle("Controles do Avatar")
        controls.show()
        print("[Avatar] Painel nao encontrado — controles em janela separada.")

    main_window._avatar_controls = controls
    return controls
