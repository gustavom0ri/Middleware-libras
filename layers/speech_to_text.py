"""
Camada 2 — Speech-to-Text com Whisper
Recebe chunks de áudio da Camada 1 e transcreve para texto em português.
"""

import whisper
import numpy as np
import threading
import queue
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Modelo padrão — troque para "tiny", "base" ou "medium" conforme necessário
DEFAULT_MODEL = "small"

# RMS mínimo para considerar que há fala (evita processar silêncio)
SILENCE_THRESHOLD = 0.01


class SpeechToText:
    """
    Consome chunks de áudio da fila da Camada 1, transcreve com Whisper
    e coloca o texto resultante em uma fila para a Camada 3 (VLibras).
    """

    def __init__(self, model_name: str = DEFAULT_MODEL):
        self.model_name = model_name
        self.text_queue: queue.Queue[str] = queue.Queue()
        self._model = None
        self._thread = None
        self._running = False

    # ------------------------------------------------------------------
    # Carregamento do modelo
    # ------------------------------------------------------------------
    def load(self):
        """
        Carrega o modelo Whisper em memória.
        Chame uma vez na inicialização — pode demorar alguns segundos
        no primeiro uso (download automático do modelo).
        """
        logger.info(f"Carregando modelo Whisper '{self.model_name}'...")
        self._model = whisper.load_model(self.model_name)
        logger.info("Modelo carregado e pronto.")

    # ------------------------------------------------------------------
    # Transcrição de um chunk
    # ------------------------------------------------------------------
    def _transcribe(self, audio_chunk: np.ndarray) -> str | None:
        """
        Transcreve um chunk de áudio float32 @ 16000Hz.
        Retorna o texto ou None se for silêncio / transcrição vazia.
        """
        # Ignora silêncio para não desperdiçar processamento
        rms = np.sqrt(np.mean(audio_chunk ** 2))
        if rms < SILENCE_THRESHOLD:
            logger.debug(f"Chunk ignorado (silêncio | RMS={rms:.4f})")
            return None

        # Whisper espera float32 normalizado entre -1 e 1
        audio_chunk = audio_chunk.astype(np.float32)
        audio_chunk = np.clip(audio_chunk, -1.0, 1.0)

        result = self._model.transcribe(
            audio_chunk,
            language="pt",          # força português — melhora acurácia
            fp16=False,             # compatível com CPUs sem suporte a fp16
            condition_on_previous_text=True,  # contexto entre chunks
        )

        text = result["text"].strip()
        if not text:
            return None

        logger.info(f"Transcrito: {text}")
        return text

    # ------------------------------------------------------------------
    # Loop de transcrição em background
    # ------------------------------------------------------------------
    def _worker(self, audio_queue: queue.Queue):
        """Thread worker que consome a fila de áudio continuamente."""
        while self._running:
            try:
                chunk = audio_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            text = self._transcribe(chunk)
            if text:
                self.text_queue.put(text)

    def start(self, audio_queue: queue.Queue):
        """
        Inicia a transcrição em background.
        Recebe a audio_queue diretamente da instância de AudioCapture.
        """
        if self._model is None:
            raise RuntimeError("Modelo não carregado. Chame .load() antes de .start().")

        if self._running:
            logger.warning("STT já está rodando.")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._worker,
            args=(audio_queue,),
            daemon=True,
            name="stt-worker",
        )
        self._thread.start()
        logger.info("STT iniciado em background.")

    def stop(self):
        """Para o worker de transcrição."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("STT encerrado.")

    def get_text(self, timeout: float = 5.0) -> str | None:
        """
        Retorna o próximo texto transcrito da fila.
        Bloqueia até timeout segundos. Retorna None se não houver texto.
        """
        try:
            return self.text_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    @property
    def is_running(self) -> bool:
        return self._running


# ------------------------------------------------------------------
# Teste integrado — Camada 1 + Camada 2
# ------------------------------------------------------------------
if __name__ == "__main__":
    import time
    import sys
    import os

    # Adiciona o diretório pai ao path para importar AudioCapture
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from layers.audio_capture import AudioCapture

    print("=== Teste da Camada 2: Speech-to-Text ===\n")

    # Carrega Whisper (faz download automático se for a primeira vez)
    stt = SpeechToText(model_name="small")
    stt.load()

    # Inicia captura de áudio
    capture = AudioCapture(chunk_seconds=3)
    try:
        capture.start()
    except RuntimeError as e:
        print(f"ERRO na captura: {e}")
        exit(1)

    # Inicia transcrição passando a fila de áudio
    stt.start(capture.audio_queue)

    print("\nOuvindo por 30 segundos... Fale ou reproduza áudio com voz!\n")

    start = time.time()
    while time.time() - start < 30:
        text = stt.get_text(timeout=1.0)
        if text:
            print(f"  📝 {text}")

    # Encerra tudo
    stt.stop()
    capture.stop()
    print("\nTeste finalizado!")