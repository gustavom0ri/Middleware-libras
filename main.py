"""
avatar_window.py — Avatar VLibras com player LOCAL e versao TRAVADA
===========================================================================
Arquivo COMPLETO e autossuficiente. Substitui o anterior por inteiro.

PRE-REQUISITOS (ja feitos):
  1) python setup_vlibras.py      -> cria ./vendor/vlibras/
  2) python fix_bundle.py         -> instala o bundle correto (vlibras.js)

O QUE ESTA VERSAO INCORPORA (descoberto nos logs reais do seu ambiente):
  * Construtor real .............. window.VLibras.Player
  * Assinatura que funciona ...... new Player({ translatorUrl, targetPath })
  * Carga do bundle .............. <script> CLASSICO (webpack 1), com
                                   fallback para import() de ES module
  * Callbacks globais do Unity ... onLoadPlayer, onPlayingStateChange,
                                   updateProgress, CounterGloss,
                                   GetAvatar, FinishWelcome
  * Deteccao de fim de traducao .. via onPlayingStateChange (evento REAL,
                                   nao mais heuristica/timeout)
  * Correcao do avatar invisivel . CSS em toda a cadeia + sincronizacao do
                                   buffer de desenho do canvas
  * vendor/ encontrado subindo diretorios (funciona com este arquivo em
    Layers/, ui/, src/ ou na raiz)

API PUBLICA (inalterada — o main.py NAO precisa mudar):
    AvatarWindow(width, height)
    .translate(texto)   .retry()   .show()   .close()
===========================================================================
"""

import sys
import os
import json
import re
import socket
import tempfile
import threading
import http.server
import socketserver
import functools

# ---------------------------------------------------------------------------
# FLAGS DO CHROMIUM
# ---------------------------------------------------------------------------
# Precisam existir ANTES de o QtWebEngine inicializar. Quando o app e aberto
# pelo main.py, quem define isso e o main.py (ja esta correto la). O
# setdefault abaixo cobre o caso de rodar este arquivo sozinho.
#
# NAO ha mais --disable-web-security: agora tudo e servido pelo mesmo
# servidor local (same-origin), entao ele deixou de ser necessario.
# ---------------------------------------------------------------------------
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--enable-gpu --ignore-gpu-blocklist --ignore-gpu-blacklist "
    "--enable-webgl --enable-features=SharedArrayBuffer",
)

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QHBoxLayout
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import (
    QWebEngineSettings, QWebEnginePage, QWebEngineProfile
)
from PyQt6.QtCore import Qt, QUrl, QPoint, pyqtSlot, QTimer, QCoreApplication
from PyQt6.QtGui import QFont


# ===========================================================================
# LOCALIZACAO DO vendor/vlibras/
# ===========================================================================
# Este arquivo pode estar em Layers/, ui/, src/ ou na raiz, enquanto o
# vendor/ e criado na RAIZ do projeto pelo setup_vlibras.py. Por isso
# subimos os diretorios ate encontrar, em vez de assumir que esta ao lado.
# ===========================================================================
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))


def _achar_vendor():
    candidatos = []

    # 1) subindo a partir da pasta deste arquivo
    d = _THIS_DIR
    for _ in range(6):
        candidatos.append(os.path.join(d, "vendor", "vlibras"))
        pai = os.path.dirname(d)
        if pai == d:
            break
        d = pai

    # 2) subindo a partir do diretorio de trabalho atual
    d = os.path.abspath(os.getcwd())
    for _ in range(6):
        c = os.path.join(d, "vendor", "vlibras")
        if c not in candidatos:
            candidatos.append(c)
        pai = os.path.dirname(d)
        if pai == d:
            break
        d = pai

    # prefere um vendor COMPLETO (com o bundle do player instalado)
    for c in candidatos:
        if os.path.isfile(os.path.join(c, "player", "build",
                                       "vlibras-player.js")):
            return c
    # senao, qualquer um que exista
    for c in candidatos:
        if os.path.isdir(c):
            return c
    return os.path.join(_THIS_DIR, "vendor", "vlibras")


VENDOR_DIR = _achar_vendor()
BASE_DIR = os.path.dirname(os.path.dirname(VENDOR_DIR))
LOCK_PATH = os.path.join(VENDOR_DIR, "LOCK.json")

# A API de traducao (texto -> glosa) e um SERVICO, nao um asset: continua
# sendo remota. Para 100% offline seria preciso hospedar o translator.
TRANSLATOR_URL = "https://traducao2.vlibras.gov.br/translate"
if os.path.isfile(LOCK_PATH):
    try:
        with open(LOCK_PATH, encoding="utf-8") as _f:
            TRANSLATOR_URL = json.load(_f).get("translator_url", TRANSLATOR_URL)
    except Exception:
        pass


# ===========================================================================
# PAGINA DO AVATAR (gerada em memoria e servida pelo servidor local)
# ===========================================================================
HTML = r"""<!DOCTYPE html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body {
  width: 100%; height: 100%;
  background: #1a2a3a;
  overflow: hidden;
}

/* ------------------------------------------------------------------
   LAYOUT DO AVATAR  (correcao da "tela vazia")
   ------------------------------------------------------------------
   O player cria uma hierarquia propria dentro do #wrapper (normalmente
   um #gameContainer com o <canvas> do Unity). Se QUALQUER no dessa
   cadeia ficar com altura 0, o avatar some da tela — mesmo com o Unity
   rodando perfeitamente. Por isso forcamos todos os niveis a preencher.
   ------------------------------------------------------------------ */
#wrapper {
  position: fixed;
  inset: 0;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

#wrapper > div,
#wrapper div[id*="game"],
#wrapper div[id*="Game"],
#wrapper div[class*="player"],
#wrapper div[class*="Player"],
#gameContainer {
  position: absolute !important;
  top: 0 !important;
  left: 0 !important;
  width: 100% !important;
  height: 100% !important;
  background: transparent !important;
}

#wrapper canvas,
canvas {
  position: absolute !important;
  top: 0 !important;
  left: 0 !important;
  width: 100% !important;
  height: 100% !important;
  display: block !important;
  visibility: visible !important;
  opacity: 1 !important;
  background: transparent !important;
}

#status {
  position: fixed; bottom: 12px; left: 0; right: 0;
  text-align: center; color: #9fb3c8;
  font: 12px "Segoe UI", sans-serif;
  z-index: 50; pointer-events: none;
}
</style>
</head>
<body>

<div id="wrapper"></div>
<div id="status">Carregando player local...</div>

<script type="module">
// =====================================================================
// Este script e um MODULO para poder usar import() dinamico como
// fallback. O bundle do webpack 1, porem, e um script CLASSICO que cria
// window.VLibras — por isso tentamos o <script> classico primeiro.
// =====================================================================

function log(m) { console.log("[VLibras JS] " + m); }
function setStatus(m) {
  const el = document.getElementById('status');
  if (el) el.textContent = m;
}

log("Pagina local carregada (origem: " + location.origin + ")");
log("crossOriginIsolated = " + self.crossOriginIsolated +
    " | SharedArrayBuffer = " + (typeof SharedArrayBuffer !== 'undefined'));

// ---------------------------------------------------------------------
// ESTADO
// ---------------------------------------------------------------------
let player = null;
let playerReady = false;
const queue = [];
let isBusy = false;
let onDoneGuard = null;
// ---------------------------------------------------------------------
// CONTROLE DE REPRODUCAO (corrige frases cortadas)
// ---------------------------------------------------------------------
// O Unity dispara onPlayingStateChange(false) LOGO AO RECEBER a frase —
// porque ele para a animacao anterior antes de comecar a nova. Se
// tratarmos esse "false" como "terminou", a proxima frase da fila e
// enviada imediatamente e ATROPELA a atual: o avatar sinaliza so um
// pedaco de cada frase.
//
// Regra correta: so aceitamos "false" DEPOIS de ter visto "true"
// (isto e, depois que a animacao realmente comecou).
let animacaoComecou = false;
// ---------------------------------------------------------------------
// CONFIRMACAO DE FIM (corrige o "pulo" na soletracao)
// ---------------------------------------------------------------------
// Na datilologia CADA LETRA e uma animacao separada, entao o Unity emite
// true/false a cada letra. Se encerrarmos no primeiro "false", cortamos
// a palavra na 2a letra. Solucao: ao receber "false", esperamos um
// intervalo; se um novo "true" chegar nesse meio tempo, era so a pausa
// entre letras/sinais e cancelamos o encerramento.
let timerFimPendente = null;
const ESPERA_CONFIRMA_FIM = 1600;   // ms de silencio para considerar fim
let unityPronto = false;        // true so apos onLoadPlayer
let avatarPendente = null;      // avatar pedido antes do Unity ficar pronto
const DEFAULT_SPEED = 2;

// ---------------------------------------------------------------------
// CARREGAMENTO DO BUNDLE
// ---------------------------------------------------------------------
const BUNDLE_PATHS = [
  './player/build/vlibras-player.js',
  './player/build/vlibras.js',
  './player/build/index.js',
  './player/build/bundle.js'
];

function carregarScriptClassico(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.onload = () => resolve(true);
    s.onerror = () => reject(new Error('falha ao carregar ' + src));
    document.head.appendChild(s);
  });
}

function acharCtorEmGlobais(novas) {
  // Caso real deste projeto: window.VLibras.Player
  const conhecidos = ['VLibras', 'VLibrasPlayer', 'Player', 'vlibras'];
  for (const n of conhecidos) {
    const o = window[n];
    if (typeof o === 'function') { log("Construtor: window." + n); return o; }
    if (o && typeof o.Player === 'function') {
      log("Construtor: window." + n + ".Player"); return o.Player;
    }
    if (o && typeof o.default === 'function') {
      log("Construtor: window." + n + ".default"); return o.default;
    }
  }
  // qualquer global NOVA que pareca um construtor
  for (const n of novas) {
    const o = window[n];
    if (typeof o === 'function' && /player|libras/i.test(n)) {
      log("Construtor (global nova): window." + n); return o;
    }
    if (o && typeof o === 'object') {
      if (typeof o.Player === 'function') {
        log("Construtor (global nova): window." + n + ".Player");
        return o.Player;
      }
      if (typeof o.default === 'function') {
        log("Construtor (global nova): window." + n + ".default");
        return o.default;
      }
    }
  }
  return null;
}

function getCtorFromModule(mod) {
  if (!mod) return null;
  if (typeof mod.default === 'function') {
    log("Construtor: export default"); return mod.default;
  }
  for (const n of ['VLibrasPlayer', 'Player', 'VLibras']) {
    if (typeof mod[n] === 'function') {
      log("Construtor: export '" + n + "'"); return mod[n];
    }
    if (mod.default && typeof mod.default[n] === 'function') {
      log("Construtor: default." + n); return mod.default[n];
    }
  }
  log("Exports do modulo: " + Object.keys(mod).join(', '));
  return null;
}

async function obterConstrutor() {
  const antes = new Set(Object.keys(window));

  // --- 1) script classico (caso do webpack 1) ------------------------
  for (const p of BUNDLE_PATHS) {
    try {
      await carregarScriptClassico(p);
      log("Bundle carregado como script classico: " + p);
      const novas = Object.keys(window).filter(k => !antes.has(k));
      log("Globais novas: " + (novas.length ? novas.join(', ') : '(nenhuma)'));
      const ctor = acharCtorEmGlobais(novas);
      if (ctor) return ctor;
      log("Carregou mas nao expos construtor; tentando import()...");
      break;
    } catch (e) {
      log("Nao carregou " + p);
    }
  }

  // --- 2) ES module --------------------------------------------------
  for (const p of BUNDLE_PATHS) {
    try {
      const mod = await import(p);
      log("Bundle importado como ES module: " + p);
      const ctor = getCtorFromModule(mod);
      if (ctor) return ctor;
    } catch (e) { /* segue tentando */ }
  }

  return null;
}

function listMethods(obj) {
  const out = [];
  try {
    const p = Object.getPrototypeOf(obj) || obj;
    Object.getOwnPropertyNames(p).forEach(k => {
      try {
        if (typeof obj[k] === 'function' && k !== 'constructor') out.push(k);
      } catch (e) {}
    });
  } catch (e) {}
  return out.join(', ');
}

// =====================================================================
// DIAGNOSTICO DE LAYOUT
// ---------------------------------------------------------------------
// O Unity pode estar rodando perfeitamente e ainda assim nada aparecer,
// se o canvas (ou um container acima dele) estiver com tamanho zero.
// Aqui inspecionamos a cadeia inteira e reportamos onde ela quebra.
// =====================================================================
function diagnosticarLayout() {
  const w = document.getElementById('wrapper');
  const c = document.querySelector('#wrapper canvas') ||
            document.querySelector('canvas');

  log("--- DIAGNOSTICO DE LAYOUT ---");
  log("janela: " + window.innerWidth + "x" + window.innerHeight);

  if (w) {
    const r = w.getBoundingClientRect();
    log("#wrapper: " + Math.round(r.width) + "x" + Math.round(r.height) +
        " | filhos: " + w.children.length);
    for (let i = 0; i < w.children.length; i++) {
      const ch = w.children[i];
      const cr = ch.getBoundingClientRect();
      const cs = getComputedStyle(ch);
      log("  [" + i + "] <" + ch.tagName.toLowerCase() + "> id='" +
          (ch.id || '') + "' " +
          Math.round(cr.width) + "x" + Math.round(cr.height) +
          " display=" + cs.display + " visibility=" + cs.visibility);
    }
  } else {
    log("#wrapper NAO existe (!)");
  }

  if (c) {
    const r = c.getBoundingClientRect();
    const cs = getComputedStyle(c);
    log("canvas CSS    : " + Math.round(r.width) + "x" + Math.round(r.height));
    log("canvas buffer : " + c.width + "x" + c.height);
    log("canvas pai    : <" + (c.parentElement
        ? c.parentElement.tagName.toLowerCase() + " id=" + c.parentElement.id
        : "?") + ">");
    log("canvas estilo : display=" + cs.display +
        " visibility=" + cs.visibility + " opacity=" + cs.opacity);
    if (r.width < 10 || r.height < 10) {
      log("PROBLEMA: canvas com tamanho ~zero na tela!");
    }
    if (c.width < 10 || c.height < 10) {
      log("PROBLEMA: buffer de desenho do canvas ~zero!");
    }
  } else {
    log("canvas NAO encontrado (!)");
  }
  log("--- FIM DO DIAGNOSTICO ---");
}

// =====================================================================
// AJUSTE FORCADO DO CANVAS
// ---------------------------------------------------------------------
// O UnityLoader define o buffer de desenho (canvas.width/height) uma
// unica vez, com base no container no momento da criacao. Se naquele
// instante o container ainda era pequeno, o avatar renderiza num buffer
// minusculo. Aqui sincronizamos buffer e CSS com a janela.
// =====================================================================
function ajustarCanvas() {
  const c = document.querySelector('#wrapper canvas') ||
            document.querySelector('canvas');
  if (!c) return false;

  const lw = window.innerWidth;
  const lh = window.innerHeight;
  if (lw < 10 || lh < 10) return false;

  // garante que a cadeia de pais preenche a tela
  let p = c.parentElement;
  let niveis = 0;
  while (p && p.id !== 'wrapper' && niveis < 6) {
    p.style.width = '100%';
    p.style.height = '100%';
    p.style.position = 'absolute';
    p.style.top = '0';
    p.style.left = '0';
    p = p.parentElement;
    niveis++;
  }

  c.style.width = '100%';
  c.style.height = '100%';
  c.style.display = 'block';

  const dpr = window.devicePixelRatio || 1;
  const bw = Math.round(lw * dpr);
  const bh = Math.round(lh * dpr);
  if (Math.abs(c.width - bw) > 2 || Math.abs(c.height - bh) > 2) {
    c.width = bw;
    c.height = bh;
    log("canvas redimensionado -> buffer " + bw + "x" + bh);
  }
  return true;
}

// O Unity as vezes reescreve o tamanho depois; reaplicamos por ~10s.
function manterCanvasAjustado() {
  let n = 0;
  const iv = setInterval(() => {
    n++;
    ajustarCanvas();
    if (n >= 20) clearInterval(iv);
  }, 500);
}

window.addEventListener('resize', ajustarCanvas);

// =====================================================================
// CALLBACKS GLOBAIS DO UNITY
// ---------------------------------------------------------------------
// O player Unity chama estas funcoes globais para reportar seu estado.
// Descobrimos os nomes inspecionando o bundle:
//   onLoadPlayer, onPlayingStateChange, updateProgress,
//   CounterGloss, GetAvatar, FinishWelcome
// Usamos onPlayingStateChange como sinal REAL de fim de traducao — bem
// mais confiavel que o timeout heuristico que existia antes.
// =====================================================================
// ---------------------------------------------------------------------
// TROCA DE AVATAR (icaro / hosana / guga)
// ---------------------------------------------------------------------
function aplicarAvatar(nome) {
  if (!nome) return false;
  if (!player || !unityPronto) {
    avatarPendente = nome;
    log("changeAvatar(" + nome + ") adiado ate o Unity ficar pronto");
    return false;
  }
  try {
    if (typeof player.changeAvatar === 'function') {
      player.changeAvatar(nome);
      log("changeAvatar(" + nome + ") aplicado");
      // trocar de avatar reinicia a cena: reaplica a velocidade depois
      setTimeout(() => aplicarVelocidadeComRetry(0), 1200);
      return true;
    }
    log("changeAvatar indisponivel nesta build");
  } catch (e) {
    log("changeAvatar falhou: " + (e && e.message ? e.message : e));
    avatarPendente = nome;
  }
  return false;
}

function instalarCallbacksUnity() {
  const origLoad = window.onLoadPlayer;
  window.onLoadPlayer = function () {
    log("[Unity] onLoadPlayer  (Unity pronto de verdade)");
    try { if (typeof origLoad === 'function') origLoad.apply(this, arguments); }
    catch (e) {}
    unityPronto = true;
    onReady();
    // Agora sim o Unity aceita comandos: aplica o que ficou pendente.
    setTimeout(() => {
      aplicarVelocidadeComRetry(0);
      if (avatarPendente) {
        const a = avatarPendente;
        avatarPendente = null;
        aplicarAvatar(a);
      }
    }, 300);
  };

  const origPlaying = window.onPlayingStateChange;
  window.onPlayingStateChange = function (isPlaying) {
    try {
      if (typeof origPlaying === 'function') origPlaying.apply(this, arguments);
    } catch (e) {}

    const tocando = (isPlaying === true || isPlaying === 1 ||
                     isPlaying === '1' || isPlaying === 'true' ||
                     isPlaying === 'True');
    const parou = (isPlaying === false || isPlaying === 0 ||
                   isPlaying === '0' || isPlaying === 'false' ||
                   isPlaying === 'False');

    if (tocando) {
      animacaoComecou = true;
      // Chegou um novo sinal/letra: cancela o encerramento agendado.
      if (timerFimPendente) {
        clearTimeout(timerFimPendente);
        timerFimPendente = null;
      }
      return;
    }

    if (parou) {
      if (!animacaoComecou) {
        // "false" antes de comecar: e so a limpeza da animacao anterior.
        log("[Unity] parou (ainda nao comecou — ignorado)");
        return;
      }
      // Pode ser apenas a pausa entre duas letras da soletracao.
      // So encerramos se NENHUM novo "true" chegar dentro da janela.
      if (timerFimPendente) clearTimeout(timerFimPendente);
      timerFimPendente = setTimeout(() => {
        timerFimPendente = null;
        log("[Unity] fim confirmado (sem novos sinais)");
        if (onDoneGuard) onDoneGuard();
      }, ESPERA_CONFIRMA_FIM);
    }
  };

  const origProg = window.updateProgress;
  window.updateProgress = function (p) {
    try { if (typeof origProg === 'function') origProg.apply(this, arguments); }
    catch (e) {}
    if (!playerReady && typeof p === 'number') {
      setStatus("Carregando avatar... " + Math.round(p * 100) + "%");
    }
  };

  log("Callbacks do Unity instalados");
}

// =====================================================================
// INICIALIZACAO
// =====================================================================
async function initPlayer() {
  const Ctor = await obterConstrutor();
  if (!Ctor) {
    setStatus("Erro: construtor do player nao encontrado");
    console.log("__LOAD_ERROR__bundle carregou mas nao expos construtor");
    return;
  }

  instalarCallbacksUnity();

  const wrapper = document.getElementById('wrapper');

  // Assinatura 1 e a que funciona neste projeto; as demais sao fallback.
  const tentativas = [
    () => new Ctor({ translatorUrl: '%%TRANSLATOR_URL%%',
                     targetPath: './target' }),
    () => new Ctor(wrapper, { translatorUrl: '%%TRANSLATOR_URL%%',
                              targetPath: './target' }),
    () => new Ctor(wrapper, './target'),
    () => new Ctor('./target'),
    () => new Ctor(wrapper),
    () => new Ctor()
  ];

  for (let i = 0; i < tentativas.length; i++) {
    try {
      player = tentativas[i]();
      log("Player instanciado (assinatura " + (i + 1) + ")");
      // ----------------------------------------------------------
      // EXPOSICAO DA INSTANCIA
      // ----------------------------------------------------------
      // Scripts externos (ex.: avatar_extras.py) precisam alcancar a
      // instancia real. Como `player` e uma variavel de escopo de
      // modulo, ela seria invisivel de fora — o que causava o erro
      // "instancia ainda nao capturada". Publicamos em varios nomes
      // para cobrir as convencoes usadas por esses scripts.
      window.player = player;
      window.__player = player;
      window.vlibrasPlayer = player;
      window.__vlibrasPlayer = player;
      if (window.VLibras) { window.VLibras.instance = player; }
      log("Instancia exposta em window.player / window.__player");
      break;
    } catch (e) {
      log("Assinatura " + (i + 1) + " falhou: " +
          (e && e.message ? e.message : e));
    }
  }

  if (!player) {
    setStatus("Erro ao instanciar o player");
    console.log("__LOAD_ERROR__nenhuma assinatura de construtor funcionou");
    return;
  }

  log("Metodos disponiveis: " + listMethods(player));
  hookEvents();

  try {
    if (typeof player.load === 'function') {
      player.load(wrapper);
      log("player.load(wrapper) chamado");
    } else {
      log("AVISO: player.load nao existe; aguardando canvas mesmo assim");
    }
  } catch (e) {
    log("player.load falhou: " + e);
  }

  setStatus("Carregando avatar (Unity)...");
  waitForCanvas(0);
}

function hookEvents() {
  if (!player || typeof player.on !== 'function') {
    log("AVISO: player.on indisponivel (usando so callbacks do Unity).");
    return;
  }
  try { player.on('load', () => { log("Evento 'load'"); onReady(); }); }
  catch (e) {}
  try { player.on('error', (err) => log("Evento 'error': " + err)); }
  catch (e) {}

  // ATENCAO: 'animation:end' e 'translate:end' disparam VARIAS vezes por
  // frase (uma por sinal, e outra quando a glosa chega). Se qualquer um
  // deles encerrar o item da fila, a frase e cortada. Por isso eles so
  // valem DEPOIS que a animacao comecou de fato.
  ['gloss:end', 'finish-translation', 'finish', 'stop'].forEach(ev => {
    try {
      player.on(ev, () => {
        if (!animacaoComecou) {
          log("Evento '" + ev + "' antes de comecar — ignorado");
          return;
        }
        // Mesmo criterio do callback: confirma antes de encerrar.
        if (timerFimPendente) clearTimeout(timerFimPendente);
        timerFimPendente = setTimeout(() => {
          timerFimPendente = null;
          log("Fim confirmado via evento '" + ev + "'");
          if (onDoneGuard) onDoneGuard();
        }, ESPERA_CONFIRMA_FIM);
      });
    } catch (e) {}
  });

  // Estes sao apenas informativos: NAO encerram o item da fila.
  ['animation:end', 'translate:end'].forEach(ev => {
    try {
      player.on(ev, () => log("(info) evento: " + ev));
    } catch (e) {}
  });
}

function waitForCanvas(tries) {
  if (playerReady) return;
  if (document.querySelector('#wrapper canvas') ||
      document.querySelector('canvas')) {
    onReady();
    return;
  }
  if (tries > 0 && tries % 20 === 0) {
    setStatus("Carregando avatar... (" + (tries / 2) + "s)");
  }
  if (tries < 360) {                    // ate ~180s
    setTimeout(() => waitForCanvas(tries + 1), 500);
  } else {
    log("Canvas nao apareceu apos ~180s.");
    setStatus("Falha ao carregar o avatar");
    console.log("__LOAD_ERROR__canvas nao renderizou (WebGL/GPU?)");
  }
}

function onReady() {
  if (playerReady) return;
  playerReady = true;
  log("PLAYER PRONTO (local, versao travada)");
  setStatus("");
  console.log("__READY__");

  // A velocidade so e aplicada de fato quando o Unity avisar que esta
  // pronto (onLoadPlayer). Aqui apenas iniciamos as retentativas.
  aplicarVelocidadeComRetry(0);

  // O Unity leva alguns instantes para criar/dimensionar o canvas.
  setTimeout(() => { diagnosticarLayout(); ajustarCanvas(); }, 1500);
  setTimeout(() => { ajustarCanvas(); manterCanvasAjustado(); }, 3000);
  setTimeout(diagnosticarLayout, 8000);

  pump();
}

let velocidadeAtual = DEFAULT_SPEED;

// ---------------------------------------------------------------------
// VELOCIDADE
// ---------------------------------------------------------------------
// ATENCAO AO TIMING: quando o <canvas> aparece, o Unity ainda NAO
// terminou de inicializar. Chamar setSpeed nesse instante lanca excecao
// (era isso que produzia "applySpeed -> sem API" mesmo com o metodo
// existindo). Por isso reaplicamos quando o Unity avisa que carregou
// (onLoadPlayer) e tambem com algumas retentativas.
// ---------------------------------------------------------------------
function aplicarVelocidade(valor, silencioso) {
  if (typeof valor === 'number' && valor > 0) velocidadeAtual = valor;
  if (!player) return false;
  try {
    if (typeof player.setSpeed === 'function') {
      player.setSpeed(velocidadeAtual);
      if (!silencioso) log("setSpeed(" + velocidadeAtual + ") aplicado");
      return true;
    }
    if (typeof player.changeSpeed === 'function') {
      player.changeSpeed(velocidadeAtual);
      if (!silencioso) log("changeSpeed(" + velocidadeAtual + ") aplicado");
      return true;
    }
  } catch (e) {
    if (!silencioso) {
      log("setSpeed(" + velocidadeAtual + ") falhou agora (Unity ainda " +
          "inicializando); sera reaplicado. " + (e && e.message ? e.message : e));
    }
  }
  return false;
}

function aplicarVelocidadeComRetry(tentativas) {
  tentativas = tentativas || 0;
  if (aplicarVelocidade(undefined, tentativas > 0)) return;
  if (tentativas < 15) {
    setTimeout(() => aplicarVelocidadeComRetry(tentativas + 1), 700);
  } else {
    log("Nao foi possivel aplicar a velocidade apos varias tentativas.");
  }
}

function applySpeed() {
  return aplicarVelocidade();
}

// =====================================================================
// FILA FIFO — uma traducao por vez, em ordem, sem perder nada
// =====================================================================
function pump() {
  if (isBusy || !playerReady || queue.length === 0) return;
  isBusy = true;
  const text = queue.shift();
  log("Processando (" + queue.length + " na fila): " + text);
  console.log("__NOW_PLAYING__" + text);

  let done = false;
  let safety = null;

  function onDone(reason) {
    if (done) return;
    done = true;
    onDoneGuard = null;
    if (safety) clearTimeout(safety);
    if (timerFimPendente) { clearTimeout(timerFimPendente); timerFimPendente = null; }
    log("Fim da traducao (" + (reason || 'ok') + ")");
    isBusy = false;
    if (queue.length === 0) console.log("__IDLE__");
    setTimeout(pump, 250);
  }

  onDoneGuard = () => onDone('unity-callback');

  // Cada frase comeca "nao iniciada": o primeiro onPlayingStateChange(false)
  // que chegar antes do inicio sera ignorado.
  animacaoComecou = false;
  if (timerFimPendente) { clearTimeout(timerFimPendente); timerFimPendente = null; }

  aplicarVelocidade(undefined, true);   // silencioso a cada frase
  try {
    if (typeof player.translate === 'function') {
      player.translate(text);
      if (typeof player.play === 'function') {
        try { player.play(); } catch (e) {}
      }
    } else {
      log("ERRO: player.translate indisponivel");
    }
  } catch (e) {
    log("translate falhou: " + e);
  }

  // Rede de seguranca: se o callback do Unity nao vier, destrava sozinho.
  // Rede de seguranca. Precisa ser generosa: cada sinal e um AssetBundle
  // baixado da internet, e palavras fora do dicionario sao SOLETRADAS
  // (uma animacao por letra), o que demora bem mais.
  const words = text.split(/\s+/).length;
  const letras = text.replace(/\s/g, '').length;
  const maxMs = Math.min(180000,
                         Math.max(15000, words * 4000 + letras * 250));
  safety = setTimeout(() => onDone('timeout-safety'), maxMs);
}

// =====================================================================
// API chamada pelo Python
// ---------------------------------------------------------------------
// Modulos NAO criam globais automaticamente, entao a funcao e anexada
// explicitamente ao window para o runJavaScript() enxergar.
// =====================================================================
// ---------------------------------------------------------------------
// API PUBLICA PARA OS CONTROLES (avatar_extras.py)
// ---------------------------------------------------------------------
// Expomos funcoes prontas em vez de exigir que o script externo cace a
// instancia do player. Se o Unity ainda nao estiver pronto, o pedido
// fica PENDENTE e e aplicado automaticamente no onLoadPlayer.
// ---------------------------------------------------------------------
window.setVelocidade = function (v) {
  const valor = parseFloat(v);
  if (!(valor > 0)) return false;
  velocidadeAtual = valor;
  if (!player || !unityPronto) {
    log("setSpeed(" + valor + ") adiado ate o Unity ficar pronto");
    return false;
  }
  return aplicarVelocidade(valor);
};

window.setAvatar = function (nome) {
  return aplicarAvatar(nome);
};

window.getPlayer = function () { return player; };
window.isUnityPronto = function () { return unityPronto; };

window.traduzir = function (text) {
  if (text && text.trim()) {
    queue.push(text.trim());
    log("Enfileirado (" + queue.length + " na fila): " + text);
    pump();
  }
};

// Utilitarios expostos para depuracao pelo console do Python
window.__diagnostico = diagnosticarLayout;
window.__ajustarCanvas = ajustarCanvas;

log("Script local carregado");
initPlayer();
</script>
</body>
</html>"""

HTML = HTML.replace("%%TRANSLATOR_URL%%", TRANSLATOR_URL)


# ===========================================================================
# SERVIDOR HTTP LOCAL
# ===========================================================================
# ===========================================================================
# PROXY DO DICIONARIO / TRADUTOR  (resolve o CORS e habilita cache offline)
# ===========================================================================
# POR QUE ISTO EXISTE
# -------------------
# Vendorizar o PLAYER nao vendoriza o DICIONARIO. Cada sinal (VOCE, AJUDA,
# SEGUIR...) e um AssetBundle baixado sob demanda de dicionario2.vlibras.gov.br,
# e a conversao texto->glosa e um servico em traducao2.vlibras.gov.br.
#
# Esses servidores NAO enviam 'Access-Control-Allow-Origin', entao o Chromium
# bloqueia as requisicoes vindas de http://127.0.0.1. O Unity interpreta o
# bloqueio como "SEM CONEXAO COM INTERNET" e cai no modo DATILOLOGIA
# (soletra letra por letra) — exatamente o que aparecia no log.
#
# SOLUCAO
# -------
# Encaminhamos essas chamadas pelo NOSSO servidor local:
#   1. o JS/Unity pede para 127.0.0.1 (mesma origem -> sem CORS);
#   2. o Python busca no servidor do VLibras (servidor-para-servidor, onde
#      CORS nao se aplica);
#   3. gravamos em vendor/vlibras/cache/ -> na proxima vez sai do disco,
#      funcionando OFFLINE.
# ===========================================================================
import urllib.request
import urllib.error
import hashlib

PROXY_PREFIX = "/__vl/"
CACHE_DIR = os.path.join(VENDOR_DIR, "cache")

# Hosts que podem ser acessados pelo proxy (lista fechada, por seguranca).
HOSTS_PERMITIDOS = (
    "vlibras.gov.br",
)

# O build do player aponta para os servidores de HOMOLOGACAO ("-dth"),
# que podem ficar instaveis ou fora do ar. Com True, o proxy passa a usar
# os servidores de PRODUCAO (remove o sufixo "-dth" do host).
# Se algum sinal parar de carregar, volte para False.
USAR_PRODUCAO = True

_PROXY_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept": "*/*",
}


def _host_permitido(host):
    host = (host or "").split(":")[0].lower()
    return any(host == d or host.endswith("." + d) for d in HOSTS_PERMITIDOS)


def _caminho_cache(url):
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:40]
    return os.path.join(CACHE_DIR, h)


class _Handler(http.server.SimpleHTTPRequestHandler):
    """
    Serve ./vendor/vlibras/ e faz proxy do dicionario/tradutor.

    Pontos criticos:
      1. COOP/COEP -> habilitam SharedArrayBuffer, exigido pelas threads
         WebAssembly do Unity. Sem isso o player trava no carregamento.
      2. Content-Type correto. Se .unityweb/.wasm/.js sairem com o tipo
         errado, o UnityLoader recusa os binarios e o import() falha.
      3. Reescrita das URLs do bundle -> tudo passa a ser same-origin.
    """

    # -- cabecalhos ----------------------------------------------------
    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        # Permite que o Unity leia as respostas do proxy sem reclamar.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def guess_type(self, path):
        p = str(path)
        if p.endswith(".unityweb"):
            return "application/octet-stream"
        if p.endswith(".wasm"):
            return "application/wasm"
        if p.endswith(".mjs") or p.endswith(".js"):
            return "application/javascript"
        if p.endswith(".json"):
            return "application/json"
        return super().guess_type(path)

    # -- CORS preflight ------------------------------------------------
    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    # -- reescrita das URLs do bundle ----------------------------------
    def _base_local(self):
        host = self.headers.get("Host") or "127.0.0.1"
        return f"http://{host}{PROXY_PREFIX}"

    def _servir_bundle_reescrito(self, caminho_fs):
        """
        Troca as URLs absolutas do VLibras por caminhos do nosso proxy.
        Assim o dicionario e o tradutor passam a ser same-origin.
        """
        try:
            with open(caminho_fs, "r", encoding="utf-8", errors="ignore") as f:
                js = f.read()
        except OSError:
            self.send_error(404)
            return

        base = self._base_local()
        # https://X.vlibras.gov.br  ->  http://127.0.0.1:PORTA/__vl/X.vlibras.gov.br
        js_novo, n = re.subn(
            r"https://([a-zA-Z0-9_.-]*vlibras\.gov\.br)",
            lambda m: base + m.group(1),
            js,
        )
        if n:
            print(f"[Avatar] Bundle: {n} URL(s) redirecionadas ao proxy local")

        body = js_novo.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -- proxy ---------------------------------------------------------
    def _resolver_url_externa(self):
        """/__vl/host/caminho?query  ->  https://host/caminho?query"""
        resto = self.path[len(PROXY_PREFIX):]
        if not resto:
            return None
        partes = resto.split("/", 1)
        host = partes[0]
        caminho = partes[1] if len(partes) > 1 else ""
        if not _host_permitido(host):
            return None
        if USAR_PRODUCAO and "-dth." in host:
            host = host.replace("-dth.", ".")
        return f"https://{host}/{caminho}"

    def _proxy(self, corpo=None, metodo="GET"):
        url = self._resolver_url_externa()
        if not url:
            self.send_error(403, "host nao permitido")
            return

        usar_cache = (metodo == "GET")
        cache_path = _caminho_cache(url) if usar_cache else None

        # 1) tenta o cache (permite funcionar offline)
        if usar_cache and cache_path and os.path.isfile(cache_path):
            try:
                with open(cache_path, "rb") as f:
                    dados = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(dados)))
                self.end_headers()
                self.wfile.write(dados)
                return
            except OSError:
                pass

        # 2) busca no servidor do VLibras (servidor-para-servidor: sem CORS)
        try:
            req = urllib.request.Request(url, data=corpo, headers=dict(_PROXY_UA),
                                         method=metodo)
            ct = self.headers.get("Content-Type")
            if ct:
                req.add_header("Content-Type", ct)
            with urllib.request.urlopen(req, timeout=30) as r:
                dados = r.read()
                tipo = r.headers.get("Content-Type", "application/octet-stream")
        except urllib.error.HTTPError as e:
            self.send_error(e.code, f"proxy: {e.reason}")
            return
        except Exception as e:
            print(f"[Avatar][proxy] falha em {url}: {e}")
            self.send_error(502, "proxy falhou")
            return

        # 3) grava no cache — mas SO se for um asset de verdade.
        # Se o sinal nao existe, o servidor pode responder 200 com uma
        # pagina HTML de erro. Cachear isso envenenaria o cache e o
        # Unity acusaria "Failed to decompress data" para sempre.
        if usar_cache and cache_path and dados:
            eh_html = dados[:200].lstrip()[:15].lower().startswith(
                (b"<!doctype", b"<html", b"<?xml"))
            if eh_html or len(dados) < 128:
                print(f"[Avatar][proxy] resposta suspeita (nao cacheada): {url}")
            else:
                try:
                    os.makedirs(CACHE_DIR, exist_ok=True)
                    with open(cache_path, "wb") as f:
                        f.write(dados)
                except OSError:
                    pass

        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    # -- rotas ---------------------------------------------------------
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path.startswith(PROXY_PREFIX):
            self._proxy(metodo="GET")
            return

        # O bundle do player e servido com as URLs reescritas.
        if self.path.split("?")[0].endswith("vlibras-player.js"):
            rel = self.path.split("?")[0].lstrip("/")
            caminho_fs = os.path.join(VENDOR_DIR, *rel.split("/"))
            if os.path.isfile(caminho_fs):
                self._servir_bundle_reescrito(caminho_fs)
                return

        super().do_GET()

    def do_POST(self):
        if self.path.startswith(PROXY_PREFIX):
            tam = int(self.headers.get("Content-Length") or 0)
            corpo = self.rfile.read(tam) if tam else None
            self._proxy(corpo=corpo, metodo="POST")
            return
        self.send_error(405)

    def log_message(self, *args):
        pass


def _start_local_server(root_dir):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    handler = functools.partial(_Handler, directory=root_dir)
    httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
    httpd.allow_reuse_address = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}/", httpd


# ===========================================================================
# NORMALIZACAO PARA GLOSA
# ===========================================================================
# POR QUE ISTO EXISTE
# -------------------
# O dicionario do VLibras e indexado por SINAL, nao por palavra escrita.
# Se o texto chegar cru, o player procura um sinal chamado literalmente
# "POETICO," (com virgula) ou "PERSONAGEM." (com ponto) — que nao existem.
# O download falha, o Unity reporta "SEM CONEXAO COM INTERNET" e cai na
# DATILOLOGIA (soletra letra por letra).
#
# A glosa e a forma escrita da Libras: SEM pontuacao, em MAIUSCULAS, sem
# artigos e sem preposicoes (que nao possuem sinal proprio na Libras).
#
# Ex.:  "até poético, porque no jogo ela pode curar o seu personagem."
#   ->  "ATE POETICO PORQUE JOGO ELA PODER CURAR SEU PERSONAGEM"
#
# OBS: esta e uma normalizacao SIMPLIFICADA. Ela nao substitui um tradutor
# gramatical completo (a Libras tem sintaxe propria), mas resolve os erros
# de download e reduz muito a datilologia.
# ===========================================================================
import unicodedata

# Artigos e preposicoes/contracoes que NAO tem sinal proprio na Libras.
_PALAVRAS_REMOVIDAS = {
    # artigos
    "o", "a", "os", "as", "um", "uma", "uns", "umas",
    # preposicoes simples
    "de", "do", "da", "dos", "das",
    "em", "no", "na", "nos", "nas",
    "ao", "aos", "à", "às", "a",
    "pelo", "pela", "pelos", "pelas",
    "num", "numa", "nuns", "numas",
    "dum", "duma",
    # conectivos sem sinal proprio
    "que", "se", "e",
}

# Verbos flexionados -> infinitivo (a Libras nao flexiona verbos).
# Lista curta e conservadora: so casos muito frequentes.
_VERBOS_INFINITIVO = {
    "é": "ser", "são": "ser", "era": "ser", "eram": "ser",
    "foi": "ser", "foram": "ser", "sou": "ser", "somos": "ser",
    "está": "estar", "estão": "estar", "estava": "estar",
    "estou": "estar", "estamos": "estar",
    "tem": "ter", "têm": "ter", "tinha": "ter", "tenho": "ter",
    "temos": "ter", "teve": "ter",
    "pode": "poder", "podem": "poder", "posso": "poder",
    "podia": "poder", "pôde": "poder",
    "vai": "ir", "vão": "ir", "vou": "ir", "vamos": "ir",
    "faz": "fazer", "fazem": "fazer", "faço": "fazer",
    "quer": "querer", "querem": "querer", "quero": "querer",
}


def texto_para_glosa(texto: str, remover_acentos: bool = False) -> str:
    """
    Converte texto em portugues para uma glosa simplificada.

    remover_acentos=False por padrao: o dicionario TEM sinais acentuados
    (ex.: "ATE" carregou corretamente como "ATÉ" no teste real).
    """
    if not texto:
        return ""

    # 1) separa pontuacao grudada nas palavras (a causa principal das falhas)
    limpo = re.sub(r"[.,;:!?()\[\]{}\"'`~^<>/\\|@#$%&*_+=]", " ", texto)
    limpo = limpo.replace("\u2026", " ")          # reticencias unicode
    limpo = limpo.replace("\u2013", " ").replace("\u2014", " ")   # travessoes

    palavras = []
    for p in limpo.split():
        base = p.strip().lower()
        if not base:
            continue

        # 2) numeros permanecem como estao
        if base.isdigit():
            palavras.append(base)
            continue

        # 3) descarta artigos/preposicoes sem sinal proprio
        if base in _PALAVRAS_REMOVIDAS:
            continue

        # 4) verbos flexionados -> infinitivo
        base = _VERBOS_INFINITIVO.get(base, base)

        # 5) descarta residuos de pontuacao isolada
        if not any(c.isalnum() for c in base):
            continue

        palavras.append(base)

    glosa = " ".join(palavras).upper()

    if remover_acentos:
        glosa = "".join(
            c for c in unicodedata.normalize("NFD", glosa)
            if unicodedata.category(c) != "Mn"
        )

    return glosa.strip()


# ===========================================================================
# ConsolePage — ponte JS -> Python
# ===========================================================================
class ConsolePage(QWebEnginePage):
    NOW_PLAYING = "__NOW_PLAYING__"
    IDLE = "__IDLE__"
    READY = "__READY__"
    LOAD_ERROR = "__LOAD_ERROR__"

    def __init__(self, profile, parent=None, caption_cb=None, ready_cb=None):
        super().__init__(profile, parent)
        self._caption_cb = caption_cb
        self._ready_cb = ready_cb

    def javaScriptConsoleMessage(self, level, message, line, source):
        if message.startswith(self.NOW_PLAYING):
            if self._caption_cb:
                self._caption_cb(message[len(self.NOW_PLAYING):])
            return
        if message == self.IDLE:
            if self._caption_cb:
                self._caption_cb("Aguardando proxima traducao...")
            return
        if message == self.READY:
            if self._caption_cb:
                self._caption_cb("Avatar pronto. Transcricao em tempo real.")
            if self._ready_cb:
                self._ready_cb()
            return
        if message.startswith(self.LOAD_ERROR):
            motivo = message[len(self.LOAD_ERROR):]
            if self._caption_cb:
                self._caption_cb("Falha ao carregar: " + motivo)
            print(f"[Avatar][ERRO] {motivo}")
            return
        print(f"[JS] {message}")


# ===========================================================================
# AvatarWindow
# ===========================================================================
class AvatarWindow(QWidget):
    def __init__(self, width=360, height=520):
        super().__init__()
        self._drag_pos = QPoint()
        self._width = width
        self._height = height

        # Estado consultado/alterado pelos controles externos
        # (avatar_extras.instalar_controles).
        self._ready = False
        self._speed = 2.0
        self._avatar_name = "icaro"
        # Se o texto ja vier em glosa de um tradutor externo, defina
        # avatar.normalizar_glosa = False para nao processar duas vezes.
        self.normalizar_glosa = True

        self._check_vendor()
        self._base_url, self._httpd = _start_local_server(VENDOR_DIR)
        print(f"[Avatar] Servindo player local de: {VENDOR_DIR}")
        print(f"[Avatar] URL: {self._base_url}")

        self._setup_window()
        self._setup_ui()

    # -- validacao do vendor ------------------------------------------
    def _check_vendor(self):
        bundle = os.path.join(VENDOR_DIR, "player", "build",
                              "vlibras-player.js")
        if not os.path.isdir(VENDOR_DIR) or not os.path.isfile(bundle):
            print("=" * 64)
            print("ERRO: player local nao encontrado.")
            print("=" * 64)
            print(f"  avatar_window.py : {_THIS_DIR}")
            print(f"  diretorio atual  : {os.getcwd()}")
            print(f"  vendor procurado : {VENDOR_DIR}")
            print(f"  vendor existe?   : {os.path.isdir(VENDOR_DIR)}")
            print(f"  bundle           : {bundle}")
            print(f"  bundle existe?   : {os.path.isfile(bundle)}")
            print("=" * 64)
            print("Rode:  python setup_vlibras.py   e depois  python fix_bundle.py")
            print("=" * 64)
            sys.exit(1)

        if os.path.isfile(LOCK_PATH):
            try:
                with open(LOCK_PATH, encoding="utf-8") as f:
                    lock = json.load(f)
                print(f"[Avatar] Versao travada: {lock.get('player_repo')} "
                      f"@ {lock.get('player_ref')}")
            except Exception:
                pass

    # -- janela --------------------------------------------------------
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
        self.move(screen.width() - self._width - 30,
                  screen.height() - self._height - 100)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        cache_path = os.path.join(tempfile.gettempdir(), "vlibras_local")
        os.makedirs(cache_path, exist_ok=True)

        self._profile = QWebEngineProfile("vlibras_local", self)
        self._profile.setCachePath(cache_path)
        self._profile.setPersistentStoragePath(cache_path)

        self._page = ConsolePage(self._profile, self,
                                 caption_cb=self._update_caption,
                                 ready_cb=self._on_ready)
        settings = self._page.settings()
        for attr in (QWebEngineSettings.WebAttribute.JavascriptEnabled,
                     QWebEngineSettings.WebAttribute.PluginsEnabled,
                     QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
                     QWebEngineSettings.WebAttribute.WebGLEnabled,
                     QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled,
                     QWebEngineSettings.WebAttribute.ShowScrollBars):
            try:
                if attr == QWebEngineSettings.WebAttribute.ShowScrollBars:
                    settings.setAttribute(attr, False)
                else:
                    settings.setAttribute(attr, True)
            except Exception:
                pass

        self._webview = QWebEngineView()
        self._webview.setPage(self._page)
        self._webview.load(QUrl(self._base_url))
        layout.addWidget(self._webview, stretch=1)

        sub_container = QWidget()
        sub_container.setStyleSheet(
            "background: rgba(0,0,0,0.9); border-top: 2px solid #00FF88;")
        sub_layout = QHBoxLayout(sub_container)
        sub_layout.setContentsMargins(16, 12, 16, 12)

        self._subtitle = QLabel("Carregando player local...")
        self._subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle.setWordWrap(True)
        self._subtitle.setFont(QFont("Segoe UI", 13, QFont.Weight.DemiBold))
        self._subtitle.setStyleSheet("color: #FFFFFF;")
        sub_layout.addWidget(self._subtitle)

        layout.addWidget(sub_container)

    # -- API publica ---------------------------------------------------
    @pyqtSlot(str)
    def translate(self, text: str):
        """
        Envia texto ao avatar.

        O texto e convertido para GLOSA antes de seguir: sem pontuacao,
        em maiusculas e sem artigos/preposicoes. Sem isso, o player
        procura sinais inexistentes como "POETICO," e cai na datilologia.

        Use normalizar_glosa=False (atributo da janela) se o texto ja
        vier em glosa de um tradutor externo.
        """
        if not text or not text.strip():
            return

        original = text.strip()

        if getattr(self, "normalizar_glosa", True):
            glosa = texto_para_glosa(original)
            if not glosa:
                print(f"[Avatar] Nada a sinalizar em: {original}")
                return
            if glosa.lower() != original.lower():
                print(f"[Avatar] Glosa: {original}  ->  {glosa}")
        else:
            glosa = original

        print(f"[Avatar] Enfileirando: {glosa}")

        esc = (glosa.replace("\\", "\\\\")
                    .replace("'", "\\'")
                    .replace('"', '\\"')
                    .replace("\n", " "))
        self._page.runJavaScript(
            f"window.traduzir && window.traduzir('{esc}');")

    def _update_caption(self, text: str):
        self._subtitle.setText(text)

    def _on_ready(self):
        """Chamado quando o JS emite __READY__ (avatar operacional)."""
        self._ready = True
        # Reaplica preferencias escolhidas nos controles antes de ficar pronto.
        if abs(self._speed - 2.0) > 1e-6:
            self.set_speed(self._speed)
        if self._avatar_name and self._avatar_name != "icaro":
            self.set_avatar(self._avatar_name)

    def is_ready(self) -> bool:
        """True quando o avatar terminou de carregar."""
        return self._ready

    # ------------------------------------------------------------------
    # CONTROLES (usados por avatar_extras.instalar_controles)
    # ------------------------------------------------------------------
    def set_speed(self, value: float):
        """
        Ajusta a velocidade da sinalizacao.

        NAO recria mais a WebView: o JS enfileira o pedido caso o Unity
        ainda esteja inicializando e o aplica sozinho no onLoadPlayer.
        """
        try:
            value = float(value)
        except (TypeError, ValueError):
            return
        if value <= 0:
            return
        self._speed = value
        print(f"[Avatar] Velocidade -> {value:.1f}x")
        self._page.runJavaScript(
            f"window.setVelocidade && window.setVelocidade({value});")

    def set_avatar(self, name: str):
        """Troca o avatar: 'icaro', 'hosana' ou 'guga'."""
        if not name:
            return
        name = str(name).strip().lower()
        self._avatar_name = name
        print(f"[Avatar] Avatar -> {name}")
        esc = name.replace("'", "")
        self._page.runJavaScript(
            f"window.setAvatar && window.setAvatar('{esc}');")

    def reload_avatar(self):
        """Recarrega a pagina do avatar (mesmo efeito de retry)."""
        self.retry()

    def get_speed(self) -> float:
        return self._speed

    def get_avatar(self) -> str:
        return self._avatar_name

    def retry(self):
        print("[Avatar] Recarregando...")
        self._ready = False
        self._webview.load(QUrl(self._base_url))
        self._subtitle.setText("Recarregando...")

    def diagnosticar(self):
        """Dispara o diagnostico de layout manualmente (depuracao)."""
        self._page.runJavaScript("window.__diagnostico && window.__diagnostico();")

    def ajustar_canvas(self):
        """Forca o reajuste do canvas manualmente (depuracao)."""
        self._page.runJavaScript(
            "window.__ajustarCanvas && window.__ajustarCanvas();")

    # -- arrastar a janela ---------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (event.globalPosition().toPoint()
                              - self.frameGeometry().topLeft())

    def mouseMoveEvent(self, event):
        if (event.buttons() == Qt.MouseButton.LeftButton
                and not self._drag_pos.isNull()):
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = QPoint()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Ao redimensionar a janela, o canvas do Unity precisa acompanhar.
        try:
            self._page.runJavaScript(
                "window.__ajustarCanvas && window.__ajustarCanvas();")
        except Exception:
            pass

    def closeEvent(self, event):
        try:
            if getattr(self, "_httpd", None):
                self._httpd.shutdown()
        except Exception:
            pass
        super().closeEvent(event)


# ===========================================================================
# Execucao isolada (teste rapido, sem o main.py)
# ===========================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    avatar = AvatarWindow()
    avatar.show()

    QTimer.singleShot(
        15000,
        lambda: avatar.translate("OLA, TESTANDO A TRADUCAO DO AVATAR")
    )

    sys.exit(app.exec())