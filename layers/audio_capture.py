"""
Camada 1 — Captura de áudio do sistema (Windows WASAPI loopback)
================================================================
Usa pyaudiowpatch para capturar o áudio dos alto-falantes automaticamente,
sem nenhuma configuração manual do usuário.

SEGMENTAÇÃO POR VAD (mudança principal desta versão)
----------------------------------------------------
Antes: blocos de 3 segundos FIXOS. O corte caía no meio das palavras, o
Whisper recebia "...ela se preu" e inventava o resto ("Oculpa"), gerando
sinais inexistentes que o avatar acabava soletrando.

Agora: o corte acontece na PAUSA da fala (VAD = Voice Activity Detection).
Cada segmento entregue ao Whisper tende a conter frases inteiras.

Como funciona:
  * o áudio é analisado em janelas curtas (30 ms);
  * mede-se a energia (RMS) de cada janela para decidir fala/silêncio;
  * ao detectar fala, abre-se um segmento;
  * após ~600 ms de silêncio contínuo, o segmento é fechado e enviado;
  * um TETO de 12 s força o corte se a pessoa não pausar (evita travar em
    fala contínua) — mas, em fala natural, o corte ocorre bem antes disso.

Latência: em fala normal há pausas a cada 2–4 s, então o segmento fecha
nesse intervalo. O teto de 12 s é apenas uma válvula de escape.
"""

import queue
import logging
import collections

import numpy as np
import pyaudiowpatch as pyaudio

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000       # Hz — ideal para Whisper
CHANNELS = 1              # mono

# ===========================================================================
# PARÂMETROS DO VAD
# ===========================================================================
FRAME_MS = 30                 # janela de análise (30 ms é o padrão em VAD)
FRAME_SIZE = int(SAMPLE_RATE * FRAME_MS / 1000)   # 480 amostras

# Energia (RMS) mínima para considerar que a janela contém fala.
# ATENÇÃO: áudio de loopback costuma ser BEM mais baixo que áudio de
# microfone. Um limiar alto demais faz o VAD nunca disparar e a captura
# fica "muda". Este piso é intencionalmente permissivo.
VAD_RMS_LIMIAR = 0.004

# Teto absoluto do limiar. Impede que a calibração trave num valor alto
# demais (o que acontecia se já houvesse áudio tocando durante a medição)
# e mate a captura por completo.
VAD_LIMIAR_MAXIMO = 0.030

# Silêncio contínuo necessário para FECHAR o segmento.
# Curto demais corta no meio da frase; longo demais aumenta a latência.
SILENCIO_FECHA_MS = 600

# Fala mínima para o segmento valer a pena (descarta estalos e cliques).
FALA_MINIMA_MS = 400

# Teto de segurança: força o corte se a pessoa não pausar.
DURACAO_MAXIMA_S = 12.0

# Duração mínima do segmento entregue (evita fragmentos inúteis).
DURACAO_MINIMA_S = 0.5

# Áudio capturado ANTES do início detectado da fala. Sem isso, o VAD corta
# o ataque da primeira sílaba (o "p" de "preocupa", por exemplo).
PRE_ROLL_MS = 300

# Calibração automática do ruído de fundo nos primeiros segundos.
CALIBRAR_RUIDO = True
CALIBRACAO_S = 1.0
CALIBRACAO_MARGEM = 1.8      # limiar = piso_de_ruído * margem

# Diagnóstico: registra os níveis observados a cada N segundos. Sem isto,
# quando nada é capturado não há como saber se o problema é o limiar.
DIAGNOSTICO_S = 5.0


class AudioCapture:
    """
    Captura áudio do sistema via WASAPI loopback.
    Detecta automaticamente o dispositivo de saída ativo (alto-falantes,
    fones, monitor HDMI etc.) — zero configuração para o usuário final.

    Entrega segmentos cortados nas PAUSAS da fala, não em tempo fixo.
    """

    def __init__(self,
                 chunk_seconds: float = DURACAO_MAXIMA_S,
                 usar_vad: bool = True,
                 vad_limiar: float = VAD_RMS_LIMIAR,
                 silencio_ms: int = SILENCIO_FECHA_MS,
                 duracao_maxima_s: float = DURACAO_MAXIMA_S):
        """
        chunk_seconds    : mantido por compatibilidade; passa a ser o TETO.
        usar_vad         : False volta ao modo antigo (blocos fixos).
        vad_limiar       : RMS mínimo para considerar fala.
        silencio_ms      : silêncio contínuo que fecha o segmento.
        duracao_maxima_s : teto de segurança.
        """
        self.usar_vad = usar_vad
        self.vad_limiar = vad_limiar
        self.silencio_ms = silencio_ms
        self.duracao_maxima_s = float(chunk_seconds or duracao_maxima_s)

        # No modo antigo, chunk_seconds volta a ser o tamanho fixo do bloco.
        self.chunk_seconds = chunk_seconds

        self.audio_queue: "queue.Queue[np.ndarray]" = queue.Queue()

        self._pa = None
        self._stream = None
        self._running = False
        self._device_info = None
        self._canais = 1

        # buffer de entrada (já reamostrado para 16 kHz)
        self._buffer = np.array([], dtype=np.float32)
        self._chunk_size = None       # usado só no modo fixo

        # --- estado do VAD -------------------------------------------
        self._em_fala = False
        self._segmento = []                     # blocos do segmento atual
        self._frames_silencio = 0
        self._frames_fala = 0
        self._amostras_segmento = 0
        self._pre_roll = collections.deque(
            maxlen=max(1, int(PRE_ROLL_MS / FRAME_MS)))

        # --- calibração de ruído --------------------------------------
        self._calibrando = CALIBRAR_RUIDO and usar_vad
        self._amostras_calibracao = []
        self._frames_calibracao_alvo = int(CALIBRACAO_S * 1000 / FRAME_MS)

        # estatísticas (úteis para o TCC)
        self.stats = {
            "segmentos": 0,
            "descartados_curtos": 0,
            "cortes_por_teto": 0,
            "duracao_media_s": 0.0,
        }
        self._soma_duracoes = 0.0

        # diagnóstico de nível de áudio
        self._diag_frames = 0
        self._diag_soma = 0.0
        self._diag_pico = 0.0

    # ------------------------------------------------------------------
    # Detecção automática do dispositivo loopback
    # ------------------------------------------------------------------
    def _find_loopback_device(self) -> dict:
        """
        Encontra automaticamente o dispositivo de loopback correspondente
        ao alto-falante padrão do sistema.
        """
        try:
            default_out = self._pa.get_default_wasapi_loopback()
        except Exception:
            default_out = None

        if default_out:
            logger.info(f"Loopback detectado: {default_out['name']}")
            return default_out

        for i in range(self._pa.get_device_count()):
            dev = self._pa.get_device_info_by_index(i)
            if dev.get("isLoopbackDevice", False):
                logger.info(f"Loopback (fallback): {dev['name']}")
                return dev

        raise RuntimeError(
            "Nenhum dispositivo de loopback encontrado.\n"
            "Verifique se o Windows Audio está ativo "
            "(services.msc → Windows Audio)."
        )

    # ------------------------------------------------------------------
    # Callback do pyaudiowpatch
    # ------------------------------------------------------------------
    def _callback(self, in_data, frame_count, time_info, status):
        if status:
            logger.warning(f"Status do stream: {status}")

        audio = np.frombuffer(in_data, dtype=np.float32)

        # Downmix para mono.
        # CORREÇÃO: a versão anterior fazia reshape(-1, 2) sempre que o
        # dispositivo tinha 2+ canais. Em placas 5.1/7.1 isso embaralha as
        # amostras e destrói o áudio. Agora usamos o nº real de canais.
        if self._canais > 1:
            usable = (len(audio) // self._canais) * self._canais
            if usable:
                audio = audio[:usable].reshape(-1, self._canais).mean(axis=1)
            else:
                return (None, pyaudio.paContinue)

        native_sr = int(self._device_info["defaultSampleRate"])
        if native_sr != SAMPLE_RATE:
            audio = self._resample(audio, native_sr, SAMPLE_RATE)

        self._buffer = np.concatenate([self._buffer, audio])

        if self.usar_vad:
            self._processar_vad()
        else:
            while len(self._buffer) >= self._chunk_size:
                chunk = self._buffer[:self._chunk_size].copy()
                self._buffer = self._buffer[self._chunk_size:]
                self.audio_queue.put(chunk)

        return (None, pyaudio.paContinue)

    # ------------------------------------------------------------------
    # VAD
    # ------------------------------------------------------------------
    def _processar_vad(self):
        """Consome o buffer em janelas de 30 ms e monta segmentos."""
        frames_silencio_fecha = max(1, int(self.silencio_ms / FRAME_MS))
        frames_fala_minima = max(1, int(FALA_MINIMA_MS / FRAME_MS))
        max_amostras = int(self.duracao_maxima_s * SAMPLE_RATE)

        while len(self._buffer) >= FRAME_SIZE:
            frame = self._buffer[:FRAME_SIZE].copy()
            self._buffer = self._buffer[FRAME_SIZE:]

            rms = float(np.sqrt(np.mean(frame ** 2)))

            # --- calibração do ruído de fundo -------------------------
            if self._calibrando:
                self._amostras_calibracao.append(rms)
                if len(self._amostras_calibracao) >= self._frames_calibracao_alvo:
                    # CORREÇÃO IMPORTANTE:
                    # A versão anterior usava a MEDIANA. Se já houvesse
                    # áudio tocando durante a calibração, a mediana refletia
                    # a FALA (não o silêncio) e o limiar subia tanto que o
                    # VAD nunca mais disparava — a captura ficava muda.
                    # Agora usamos o percentil 10 (o trecho mais silencioso
                    # observado) e limitamos o resultado por um teto.
                    piso = float(np.percentile(self._amostras_calibracao, 10))
                    novo = max(VAD_RMS_LIMIAR, piso * CALIBRACAO_MARGEM)
                    novo = min(novo, VAD_LIMIAR_MAXIMO)
                    self.vad_limiar = novo
                    self._calibrando = False
                    pico = float(np.max(self._amostras_calibracao))
                    logger.info(
                        f"VAD calibrado | piso de ruído={piso:.4f} | "
                        f"pico={pico:.4f} | limiar={novo:.4f}"
                    )
                # durante a calibração ainda alimentamos o pre-roll
                self._pre_roll.append(frame)
                continue

            # --- diagnóstico e auto-ajuste ---------------------------
            self._diag_frames += 1
            self._diag_soma += rms
            if rms > self._diag_pico:
                self._diag_pico = rms

            frames_por_diag = int(DIAGNOSTICO_S * 1000 / FRAME_MS)
            if self._diag_frames >= frames_por_diag:
                media = self._diag_soma / self._diag_frames
                logger.info(
                    f"[áudio] nível médio={media:.4f} | pico={self._diag_pico:.4f} "
                    f"| limiar={self.vad_limiar:.4f} | "
                    f"segmentos até agora={self.stats['segmentos']}"
                )

                # SALVA-VIDAS: há energia no áudio (o pico supera o piso
                # absoluto) mas nada foi capturado -> o limiar está alto
                # demais. Baixa automaticamente em vez de ficar mudo.
                if (self.stats["segmentos"] == 0
                        and self._diag_pico > VAD_RMS_LIMIAR
                        and self.vad_limiar > self._diag_pico * 0.6):
                    novo = max(VAD_RMS_LIMIAR, self._diag_pico * 0.35)
                    logger.warning(
                        f"[áudio] nenhum segmento capturado — reduzindo o "
                        f"limiar de {self.vad_limiar:.4f} para {novo:.4f}"
                    )
                    self.vad_limiar = novo

                self._diag_frames = 0
                self._diag_soma = 0.0
                self._diag_pico = 0.0

            tem_fala = rms >= self.vad_limiar

            if not self._em_fala:
                if tem_fala:
                    # Abre o segmento incluindo o pre-roll, para não perder
                    # o ataque da primeira sílaba.
                    self._em_fala = True
                    self._segmento = list(self._pre_roll)
                    self._amostras_segmento = sum(len(f) for f in self._segmento)
                    self._frames_silencio = 0
                    self._frames_fala = 1
                    self._segmento.append(frame)
                    self._amostras_segmento += len(frame)
                else:
                    self._pre_roll.append(frame)
                continue

            # --- dentro de um segmento --------------------------------
            self._segmento.append(frame)
            self._amostras_segmento += len(frame)

            if tem_fala:
                self._frames_fala += 1
                self._frames_silencio = 0
            else:
                self._frames_silencio += 1

            # fecha por PAUSA
            if self._frames_silencio >= frames_silencio_fecha:
                self._fechar_segmento(frames_fala_minima, motivo="pausa")
                continue

            # fecha por TETO de segurança
            if self._amostras_segmento >= max_amostras:
                self.stats["cortes_por_teto"] += 1
                self._fechar_segmento(frames_fala_minima, motivo="teto")

    def _fechar_segmento(self, frames_fala_minima: int, motivo: str = ""):
        """Entrega o segmento atual (se tiver fala suficiente) e reseta."""
        if not self._segmento:
            self._resetar_segmento()
            return

        audio = np.concatenate(self._segmento)
        duracao = len(audio) / SAMPLE_RATE

        fala_suficiente = self._frames_fala >= frames_fala_minima
        longo_suficiente = duracao >= DURACAO_MINIMA_S

        if fala_suficiente and longo_suficiente:
            self.audio_queue.put(audio)
            self.stats["segmentos"] += 1
            self._soma_duracoes += duracao
            self.stats["duracao_media_s"] = round(
                self._soma_duracoes / self.stats["segmentos"], 2)
            logger.info(
                f"Segmento #{self.stats['segmentos']} | {duracao:.1f}s "
                f"| corte por {motivo}"
            )
        else:
            self.stats["descartados_curtos"] += 1
            logger.debug(
                f"Segmento descartado ({duracao:.2f}s, "
                f"{self._frames_fala} frames de fala)"
            )

        # Se o corte foi pelo teto, a fala provavelmente continua: mantemos
        # o estado "em fala" para não perder o encadeamento.
        if motivo == "teto":
            self._segmento = []
            self._amostras_segmento = 0
            self._frames_fala = 0
            self._frames_silencio = 0
            self._em_fala = True
        else:
            self._resetar_segmento()

    def _resetar_segmento(self):
        self._em_fala = False
        self._segmento = []
        self._amostras_segmento = 0
        self._frames_fala = 0
        self._frames_silencio = 0
        self._pre_roll.clear()

    def flush(self):
        """
        Entrega o segmento pendente (útil ao parar a captura, para não
        perder a última frase).
        """
        if self.usar_vad and self._segmento:
            frames_fala_minima = max(1, int(FALA_MINIMA_MS / FRAME_MS))
            self._fechar_segmento(frames_fala_minima, motivo="flush")

    # ------------------------------------------------------------------
    @staticmethod
    def _resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
        """Reamostragem simples por interpolação linear."""
        if orig_sr == target_sr:
            return audio
        if len(audio) == 0:
            return audio
        duration = len(audio) / orig_sr
        target_len = int(duration * target_sr)
        if target_len <= 0:
            return np.array([], dtype=np.float32)
        return np.interp(
            np.linspace(0, len(audio) - 1, target_len),
            np.arange(len(audio)),
            audio,
        ).astype(np.float32)

    # ------------------------------------------------------------------
    # Controle do stream
    # ------------------------------------------------------------------
    def start(self):
        """Inicia a captura de áudio. Detecta o dispositivo automaticamente."""
        if self._running:
            logger.warning("Captura já está rodando.")
            return

        self._pa = pyaudio.PyAudio()
        self._device_info = self._find_loopback_device()

        native_sr = int(self._device_info["defaultSampleRate"])
        self._canais = int(self._device_info["maxInputChannels"]) or 1
        self._chunk_size = int(SAMPLE_RATE * (self.chunk_seconds or 3))
        native_chunk = int(native_sr * 0.1)  # 100 ms por callback

        self._stream = self._pa.open(
            format=pyaudio.paFloat32,
            channels=self._canais,
            rate=native_sr,
            input=True,
            input_device_index=self._device_info["index"],
            frames_per_buffer=native_chunk,
            stream_callback=self._callback,
        )

        self._stream.start_stream()
        self._running = True

        modo = (f"VAD (pausa≥{self.silencio_ms}ms, teto={self.duracao_maxima_s:.0f}s)"
                if self.usar_vad else f"blocos fixos de {self.chunk_seconds}s")
        logger.info(
            f"Captura iniciada | dispositivo: {self._device_info['name']} | "
            f"SR nativo: {native_sr}Hz → resample para {SAMPLE_RATE}Hz | "
            f"segmentação: {modo}"
        )

    def stop(self):
        """Para a captura e libera recursos."""
        try:
            self.flush()          # não perde a última frase
        except Exception:
            pass

        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        if self._pa:
            self._pa.terminate()
            self._pa = None

        self._running = False
        self._buffer = np.array([], dtype=np.float32)
        self._resetar_segmento()

        if self.usar_vad and self.stats["segmentos"]:
            logger.info(
                f"Captura encerrada | {self.stats['segmentos']} segmentos | "
                f"duração média {self.stats['duracao_media_s']}s | "
                f"cortes por teto: {self.stats['cortes_por_teto']}"
            )
        else:
            logger.info("Captura encerrada.")

    def get_chunk(self, timeout: float = 5.0):
        """
        Retorna o próximo segmento de áudio pronto para o Whisper.
        Bloqueia até timeout segundos. Retorna None se não houver dados.
        """
        try:
            return self.audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    @property
    def is_running(self) -> bool:
        return self._running


# ---------------------------------------------------------------------------
# Teste rápido
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import time

    print("=== Teste da Camada 1: Captura com VAD ===\n")
    print("Fale ou reproduza áudio no computador agora...")
    print("(os segmentos serão cortados nas PAUSAS da fala)\n")

    capture = AudioCapture()

    try:
        capture.start()
    except RuntimeError as e:
        print(f"ERRO: {e}")
        raise SystemExit(1)

    recebidos = 0
    inicio = time.time()

    while time.time() - inicio < 20:
        chunk = capture.get_chunk(timeout=1.0)
        if chunk is not None:
            recebidos += 1
            dur = len(chunk) / SAMPLE_RATE
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            print(f"  Segmento #{recebidos} | {dur:.1f}s | "
                  f"{len(chunk)} amostras | RMS: {rms:.4f}")

    capture.stop()
    print(f"\nFinalizado! {recebidos} segmentos capturados.")
    print(f"Estatísticas: {capture.stats}")