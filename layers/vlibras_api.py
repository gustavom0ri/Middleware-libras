"""
Camada 3 — Integração VLibras
Converte texto em português para glosa e repassa ao avatar (Camada 4).
Usa a API pública do VLibras: https://vlibras.gov.br/api/translate
"""

import requests
import queue
import threading
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

VLIBRAS_API_URL = "https://vlibras.gov.br/api/translate"
REQUEST_TIMEOUT = 8  # segundos


class VLibrasTranslator:
    """
    Consome textos da fila da Camada 2, traduz para glosa via API VLibras
    e coloca o resultado em uma fila para a Camada 4 (avatar).
    """

    def __init__(self):
        self.glosa_queue: queue.Queue[str] = queue.Queue()
        self._thread = None
        self._running = False

    # ------------------------------------------------------------------
    # Tradução de um texto para glosa
    # ------------------------------------------------------------------
    def _translate(self, text: str) -> str | None:
        """
        Envia texto PT-BR para a API VLibras e retorna a glosa.
        Retorna o próprio texto em caso de falha (fallback — o player
        soletrar palavra por palavra).
        """
        try:
            response = requests.get(
                VLIBRAS_API_URL,
                params={"text": text},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()

            # A API retorna {"glosa": "...", ...}
            glosa = data.get("glosa") or data.get("text") or text
            logger.info(f"Glosa: {glosa}")
            return glosa

        except requests.exceptions.ConnectionError:
            logger.warning("Sem conexão com VLibras — usando texto original como fallback.")
            return text
        except requests.exceptions.Timeout:
            logger.warning("Timeout na API VLibras — usando fallback.")
            return text
        except Exception as e:
            logger.warning(f"Erro na API VLibras: {e} — usando fallback.")
            return text

    # ------------------------------------------------------------------
    # Worker em background
    # ------------------------------------------------------------------
    def _worker(self, text_queue: queue.Queue):
        while self._running:
            try:
                text = text_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            glosa = self._translate(text)
            if glosa:
                self.glosa_queue.put(glosa)

    def start(self, text_queue: queue.Queue):
        """Inicia o tradutor passando a text_queue da Camada 2."""
        if self._running:
            logger.warning("Tradutor já está rodando.")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._worker,
            args=(text_queue,),
            daemon=True,
            name="vlibras-worker",
        )
        self._thread.start()
        logger.info("Tradutor VLibras iniciado.")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("Tradutor VLibras encerrado.")

    def get_glosa(self, timeout: float = 5.0) -> str | None:
        try:
            return self.glosa_queue.get(timeout=timeout)
        except queue.Empty:
            return None