"""
Journal — Log structuré de toutes les décisions du bot.

Chaque événement est enregistré avec timestamp, type et données.
Double écriture : mémoire (pour le dashboard) + fichier JSONL (pour analyse).
"""

import time
import json
import os
import threading


class Journal:

    def __init__(self, log_dir="logs"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self.entries = []
        self._lock   = threading.Lock()
        self._file   = None
        self._open_log_file()

    def _open_log_file(self):
        ts   = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.log_dir, f"bot_{ts}.jsonl")
        self._file = open(path, "a", encoding="utf-8")
        self.log("journal_start", {"path": path})

    def log(self, event_type, data=None):
        """Enregistre un événement."""
        entry = {
            "ts":    time.time(),
            "time":  time.strftime("%Y-%m-%d %H:%M:%S"),
            "event": event_type,
            **(data or {}),
        }
        with self._lock:
            self.entries.append(entry)
            # Limiter la mémoire
            if len(self.entries) > 5000:
                self.entries = self.entries[-3000:]
            if self._file:
                try:
                    self._file.write(json.dumps(entry, default=str) + "\n")
                    self._file.flush()
                except Exception:
                    pass

    def get_recent(self, n=100):
        """Retourne les N dernières entrées."""
        with self._lock:
            return list(self.entries[-n:])

    def close(self):
        if self._file:
            self._file.close()
            self._file = None
