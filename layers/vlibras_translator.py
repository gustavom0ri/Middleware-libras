import queue
import threading
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class VLibrasTranslator:
    def __init__(self):
        self.glosa_queue = queue.Queue()
        self._thread = None
        self._running = False

    def _worker(self, text_queue):
        while self._running:
            try:
                text = text_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            logger.info(f"Enviando ao avatar: {text}")
            self.glosa_queue.put(text)

    def start(self, text_queue):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker, args=(text_queue,), daemon=True)
        self._thread.start()
        logger.info("Tradutor VLibras iniciado.")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)

    def get_glosa(self, timeout=5.0):
        try:
            return self.glosa_queue.get(timeout=timeout)
        except queue.Empty:
            return None
