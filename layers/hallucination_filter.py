"""
hallucination_filter.py — Filtro anti-alucinacao para Whisper
===========================================================================
O QUE E "ALUCINACAO" NO WHISPER
-------------------------------
O Whisper foi treinado para SEMPRE produzir texto. Quando recebe silencio,
ruido de fundo ou audio ininteligivel, ele nao devolve vazio: ele INVENTA
uma frase plausivel. Sintomas tipicos (varios apareceram no seu log):

  * frases de legenda: "Legendas pela comunidade Amara.org"
  * bordoes de video: "Inscreva-se no canal", "Obrigado por assistir"
  * palavras inexistentes ou com grafia errada: "Fizicamente..."
  * repeticao da mesma frase varias vezes seguidas
  * texto so com pontuacao: "...", "?!"

COMO ESTE FILTRO ATUA (4 camadas independentes)
-----------------------------------------------
  1. ENERGIA DO AUDIO  - descarta chunks silenciosos ANTES de transcrever
                         (a defesa mais eficaz: sem entrada, sem invencao)
  2. METRICAS DO WHISPER - usa no_speech_prob, avg_logprob e
                         compression_ratio para medir a confianca
  3. LISTA DE FRASES   - bloqueia alucinacoes conhecidas e recorrentes
  4. REPETICAO         - detecta loops e frases identicas consecutivas

USO
---
    from layers.hallucination_filter import FiltroAlucinacao

    filtro = FiltroAlucinacao()

    # antes de transcrever:
    if not filtro.audio_tem_fala(chunk):
        continue

    # depois de transcrever:
    texto = filtro.filtrar(resultado)   # devolve None se for alucinacao
    if texto:
        ...
===========================================================================
"""

import re
import logging
import unicodedata

import numpy as np

logger = logging.getLogger(__name__)


# ===========================================================================
# PARAMETROS
# ===========================================================================
# Energia (RMS) minima para considerar que ha fala.
# O padrao antigo (0.01) era permissivo demais: ruido de ventoinha, mouse e
# o proprio "chiado" da placa passavam e viravam frase inventada.
RMS_MINIMO = 0.020

# Fracao minima do chunk que precisa ter energia acima do piso. Evita que
# um unico estalo (clique, batida na mesa) libere o chunk inteiro.
FRACAO_ATIVA_MINIMA = 0.10

# --- metricas do Whisper ---------------------------------------------------
# Probabilidade de "nao ha fala" acima disto -> descarta.
NO_SPEECH_MAX = 0.60

# Log-probabilidade media abaixo disto -> transcricao pouco confiavel.
AVG_LOGPROB_MIN = -1.0

# Razao de compressao acima disto indica texto repetitivo (loop).
COMPRESSION_RATIO_MAX = 2.4

# --- texto -----------------------------------------------------------------
MIN_CARACTERES = 2          # textos menores que isto sao ruido
MAX_REPETICOES_SEGUIDAS = 2  # mesma frase N vezes seguidas -> corta


# ===========================================================================
# FRASES DE ALUCINACAO CONHECIDAS
# ===========================================================================
# O Whisper foi treinado com muitas legendas de video: quando nao entende o
# audio, tende a reproduzir bordoes desse material.
_FRASES_ALUCINACAO = {
    # legendas / creditos
    "legendas pela comunidade amara org",
    "legendas pela comunidade amara",
    "legendado pela comunidade amara org",
    "amara org",
    "subtitles by the amara org community",
    "legendas by",
    "transcricao",
    # bordoes de canal
    "inscreva se no canal",
    "inscreva se",
    "se inscreva no canal",
    "obrigado por assistir",
    "obrigada por assistir",
    "ate o proximo video",
    "ate a proxima",
    "nao se esqueca de curtir",
    "curta e compartilhe",
    "deixe seu like",
    "ative o sininho",
    # marcadores de audio
    "musica",
    "aplausos",
    "risos",
    "silencio",
    "ruido",
    "musica de fundo",
    "musica tocando",
    # ingles residual
    "thank you",
    "thanks for watching",
    "you",
    "bye",
    "okay",
    "the end",
    "subscribe",
}

# Padroes (regex) de alucinacao — casos que variam demais para lista fixa.
_PADROES_ALUCINACAO = [
    re.compile(r"^[\W_]+$"),                      # so pontuacao: "...", "?!"
    re.compile(r"^(.)\1{3,}$"),                   # "aaaa", "!!!!"
    re.compile(r"^\s*\[.*\]\s*$"),                # "[Musica]", "[Aplausos]"
    re.compile(r"^\s*\(.*\)\s*$"),                # "(inaudivel)"
    re.compile(r"amara\s*\.?\s*org", re.I),
    re.compile(r"^\s*(uh+|ah+|eh+|hm+|mm+)\s*$", re.I),
]


def _normalizar(texto: str) -> str:
    """minusculas, sem acento e sem pontuacao — para comparar frases."""
    t = unicodedata.normalize("NFD", texto.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# ===========================================================================
# FILTRO
# ===========================================================================
class FiltroAlucinacao:
    """
    Mantem o estado necessario para detectar repeticoes entre chunks
    consecutivos. Crie UMA instancia e reutilize durante toda a sessao.
    """

    def __init__(self,
                 rms_minimo: float = RMS_MINIMO,
                 no_speech_max: float = NO_SPEECH_MAX,
                 avg_logprob_min: float = AVG_LOGPROB_MIN,
                 verbose: bool = True):
        self.rms_minimo = rms_minimo
        self.no_speech_max = no_speech_max
        self.avg_logprob_min = avg_logprob_min
        self.verbose = verbose

        self._ultimo_texto = None
        self._repeticoes = 0

        # estatisticas (uteis para o TCC)
        self.stats = {
            "chunks_silenciosos": 0,
            "descartes_no_speech": 0,
            "descartes_logprob": 0,
            "descartes_compressao": 0,
            "descartes_frase": 0,
            "descartes_repeticao": 0,
            "descartes_curto": 0,
            "aceitos": 0,
        }

    # ------------------------------------------------------------------
    # CAMADA 1 — energia do audio (antes de transcrever)
    # ------------------------------------------------------------------
    def audio_tem_fala(self, audio) -> bool:
        """
        True se o chunk parece conter fala.

        Esta e a defesa mais importante: se o audio nem chega ao Whisper,
        ele nao tem como inventar nada.
        """
        if audio is None:
            return False

        try:
            a = np.asarray(audio, dtype=np.float32).ravel()
        except Exception:
            return False

        if a.size == 0:
            return False

        # normaliza int16 -> float
        if np.max(np.abs(a)) > 1.5:
            a = a / 32768.0

        rms = float(np.sqrt(np.mean(a ** 2)))
        if rms < self.rms_minimo:
            self.stats["chunks_silenciosos"] += 1
            if self.verbose:
                logger.debug(f"[filtro] silencio (RMS={rms:.4f})")
            return False

        # exige energia distribuida, nao um estalo isolado
        janela = max(1, a.size // 50)
        blocos = a[:a.size - (a.size % janela)].reshape(-1, janela)
        rms_blocos = np.sqrt(np.mean(blocos ** 2, axis=1))
        fracao_ativa = float(np.mean(rms_blocos > self.rms_minimo))

        if fracao_ativa < FRACAO_ATIVA_MINIMA:
            self.stats["chunks_silenciosos"] += 1
            if self.verbose:
                logger.debug(f"[filtro] ruido pontual (ativo={fracao_ativa:.2f})")
            return False

        return True

    # ------------------------------------------------------------------
    # CAMADAS 2-4 — depois de transcrever
    # ------------------------------------------------------------------
    def filtrar(self, resultado):
        """
        Recebe o dict devolvido por `model.transcribe(...)` (ou uma str)
        e devolve o texto limpo, ou None se for alucinacao.
        """
        if resultado is None:
            return None

        if isinstance(resultado, str):
            texto = resultado
            segmentos = []
        else:
            texto = (resultado.get("text") or "")
            segmentos = resultado.get("segments") or []

        texto = texto.strip()
        if not texto:
            return None

        # --- CAMADA 2: metricas do Whisper ----------------------------
        if segmentos:
            no_speech = [s.get("no_speech_prob", 0.0) for s in segmentos]
            logprobs = [s.get("avg_logprob", 0.0) for s in segmentos]
            compress = [s.get("compression_ratio", 0.0) for s in segmentos]

            media_no_speech = float(np.mean(no_speech)) if no_speech else 0.0
            media_logprob = float(np.mean(logprobs)) if logprobs else 0.0
            max_compress = float(np.max(compress)) if compress else 0.0

            if media_no_speech > self.no_speech_max:
                self.stats["descartes_no_speech"] += 1
                self._log(f"descartado (no_speech={media_no_speech:.2f}): {texto}")
                return None

            if media_logprob < self.avg_logprob_min:
                self.stats["descartes_logprob"] += 1
                self._log(f"descartado (logprob={media_logprob:.2f}): {texto}")
                return None

            if max_compress > COMPRESSION_RATIO_MAX:
                self.stats["descartes_compressao"] += 1
                self._log(f"descartado (repetitivo={max_compress:.2f}): {texto}")
                return None

        # --- CAMADA 3: frases e padroes conhecidos --------------------
        norm = _normalizar(texto)

        if len(norm) < MIN_CARACTERES:
            self.stats["descartes_curto"] += 1
            return None

        if norm in _FRASES_ALUCINACAO:
            self.stats["descartes_frase"] += 1
            self._log(f"descartado (frase conhecida): {texto}")
            return None

        for padrao in _PADROES_ALUCINACAO:
            if padrao.search(texto) or padrao.search(norm):
                self.stats["descartes_frase"] += 1
                self._log(f"descartado (padrao): {texto}")
                return None

        # frase composta so por termos de alucinacao
        palavras = norm.split()
        if palavras and all(p in _FRASES_ALUCINACAO for p in palavras):
            self.stats["descartes_frase"] += 1
            self._log(f"descartado (termos): {texto}")
            return None

        # --- CAMADA 4: repeticao entre chunks -------------------------
        if norm == self._ultimo_texto:
            self._repeticoes += 1
            if self._repeticoes >= MAX_REPETICOES_SEGUIDAS:
                self.stats["descartes_repeticao"] += 1
                self._log(f"descartado (repeticao {self._repeticoes}x): {texto}")
                return None
        else:
            self._ultimo_texto = norm
            self._repeticoes = 0

        # repeticao DENTRO da propria frase ("ola ola ola ola")
        if len(palavras) >= 4:
            unicas = len(set(palavras))
            if unicas / len(palavras) < 0.35:
                self.stats["descartes_repeticao"] += 1
                self._log(f"descartado (loop interno): {texto}")
                return None

        self.stats["aceitos"] += 1
        return texto

    # ------------------------------------------------------------------
    def _log(self, msg):
        if self.verbose:
            logger.info(f"[anti-alucinacao] {msg}")

    def resumo(self) -> str:
        total_desc = sum(v for k, v in self.stats.items() if k != "aceitos")
        return (f"[anti-alucinacao] aceitos={self.stats['aceitos']} | "
                f"descartados={total_desc} | detalhes={self.stats}")


# ===========================================================================
# OPCOES RECOMENDADAS PARA model.transcribe(...)
# ===========================================================================
# Passe assim:   model.transcribe(audio, **OPCOES_WHISPER)
#
# condition_on_previous_text=False e o ajuste MAIS importante: com True
# (padrao), o Whisper usa a transcricao anterior como contexto e, ao errar
# uma vez, tende a repetir o erro em cadeia — foi o que causou as repeticoes
# que voce viu.
OPCOES_WHISPER = {
    "language": "pt",
    "task": "transcribe",
    "fp16": False,
    "condition_on_previous_text": False,
    "temperature": (0.0, 0.2, 0.4),
    "compression_ratio_threshold": COMPRESSION_RATIO_MAX,
    "logprob_threshold": AVG_LOGPROB_MIN,
    "no_speech_threshold": NO_SPEECH_MAX,
}
