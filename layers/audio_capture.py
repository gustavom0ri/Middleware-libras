"""
Camada 1 — Captura de áudio do sistema (Windows WASAPI loopback)
Usa pyaudiowpatch para capturar o áudio dos alto-falantes automaticamente,
sem nenhuma configuração manual do usuário.
"""

import pyaudiowpatch as pyaudio
import numpy as np
import queue
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000       # Hz — ideal para Whisper
CHUNK_SECONDS = 3         # segundos por bloco enviado ao STT
CHANNELS = 1              # mono


class AudioCapture:
    """
    Captura áudio do sistema via WASAPI loopback.
    Detecta automaticamente o dispositivo de saída ativo (alto-falantes,
    fones, monitor HDMI etc.) — zero configuração para o usuário final.
    """

    def __init__(self, chunk_seconds: int = CHUNK_SECONDS):
        self.chunk_seconds = chunk_seconds
        self.audio_queue: queue.Queue[np.ndarray] = queue.Queue()
        self._pa = None
        self._stream = None
        self._running = False
        self._buffer = np.array([], dtype=np.float32)
        self._chunk_size = None       # definido após detectar SR do dispositivo
        self._device_info = None

    # ------------------------------------------------------------------
    # Detecção automática do dispositivo loopback
    # ------------------------------------------------------------------
    def _find_loopback_device(self) -> dict:
        """
        Encontra automaticamente o dispositivo de loopback correspondente
        ao alto-falante padrão do sistema.
        Lança RuntimeError se não encontrar (não deve acontecer no Windows 10/11).
        """
        # Pega o dispositivo de saída padrão do sistema
        default_out = self._pa.get_default_wasapi_loopback()
        if default_out:
            logger.info(f"Loopback detectado: {default_out['name']}")
            return default_out

        # Fallback: varre todos os dispositivos procurando loopback
        for i in range(self._pa.get_device_count()):
            dev = self._pa.get_device_info_by_index(i)
            if dev.get("isLoopbackDevice", False):
                logger.info(f"Loopback (fallback): {dev['name']}")
                return dev

        raise RuntimeError(
            "Nenhum dispositivo de loopback encontrado.\n"
            "Verifique se o Windows Audio está ativo (services.msc → Windows Audio)."
        )

    # ------------------------------------------------------------------
    # Callback chamado pelo pyaudiowpatch a cada frame
    # ------------------------------------------------------------------
    def _callback(self, in_data, frame_count, time_info, status):
        if status:
            logger.warning(f"Status do stream: {status}")

        # Converte bytes → float32 numpy
        audio = np.frombuffer(in_data, dtype=np.float32)

        # Se vier estéreo, faz downmix para mono
        if self._device_info["maxInputChannels"] >= 2:
            audio = audio.reshape(-1, 2).mean(axis=1)

        # Reamostrar de SR nativo → 16000 Hz se necessário
        native_sr = int(self._device_info["defaultSampleRate"])
        if native_sr != SAMPLE_RATE:
            audio = self._resample(audio, native_sr, SAMPLE_RATE)

        self._buffer = np.concatenate([self._buffer, audio])

        # Enfileira chunks completos
        while len(self._buffer) >= self._chunk_size:
            chunk = self._buffer[: self._chunk_size].copy()
            self._buffer = self._buffer[self._chunk_size :]
            self.audio_queue.put(chunk)

        return (None, pyaudio.paContinue)

    @staticmethod
    def _resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
        """Reamostragem simples por interpolação linear."""
        if orig_sr == target_sr:
            return audio
        duration = len(audio) / orig_sr
        target_len = int(duration * target_sr)
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
        self._chunk_size = SAMPLE_RATE * self.chunk_seconds
        native_chunk = int(native_sr * 0.1)  # frames por callback (100ms)

        self._stream = self._pa.open(
            format=pyaudio.paFloat32,
            channels=self._device_info["maxInputChannels"],
            rate=native_sr,
            input=True,
            input_device_index=self._device_info["index"],
            frames_per_buffer=native_chunk,
            stream_callback=self._callback,
        )

        self._stream.start_stream()
        self._running = True
        logger.info(
            f"Captura iniciada | dispositivo: {self._device_info['name']} | "
            f"SR nativo: {native_sr}Hz → resample para {SAMPLE_RATE}Hz"
        )

    def stop(self):
        """Para a captura e libera recursos."""
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        if self._pa:
            self._pa.terminate()
            self._pa = None
        self._running = False
        self._buffer = np.array([], dtype=np.float32)
        logger.info("Captura encerrada.")

    def get_chunk(self, timeout: float = 5.0) -> np.ndarray | None:
        """
        Retorna o próximo chunk de áudio pronto para o Whisper.
        Bloqueia até timeout segundos. Retorna None se não houver dados.
        """
        try:
            return self.audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    @property
    def is_running(self) -> bool:
        return self._running


# ------------------------------------------------------------------
# Teste rápido
# ------------------------------------------------------------------
if __name__ == "__main__":
    import time

    print("=== Teste da Camada 1: Captura de Áudio ===\n")
    print("Reproduza qualquer áudio no computador agora...\n")

    capture = AudioCapture(chunk_seconds=1)

    try:
        capture.start()
    except RuntimeError as e:
        print(f"ERRO: {e}")
        exit(1)

    chunks_recebidos = 0
    start = time.time()

    while time.time() - start < 10:
        chunk = capture.get_chunk(timeout=1.0)
        if chunk is not None:
            chunks_recebidos += 1
            rms = np.sqrt(np.mean(chunk ** 2))
            nivel = "🔊 OK" if rms > 0.001 else "🔇 silêncio"
            print(f"  Chunk #{chunks_recebidos} | {len(chunk)} amostras | RMS: {rms:.4f} {nivel}")

    capture.stop()
    print(f"\nFinalizado! {chunks_recebidos} chunks capturados.")
    print("Se viu '🔊 OK', a camada 1 está funcionando perfeitamente!")