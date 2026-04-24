"""
Session stats tracker: fame/hour, silver/hour, historique.
"""
import time
from collections import deque
from dataclasses import dataclass, field
from typing import List


@dataclass
class StatEvent:
    timestamp: float
    fame: int = 0
    silver: int = 0
    source: str = ""


class SessionTracker:
    def __init__(self):
        self.reset()

    def reset(self):
        self.start_time: float = 0.0
        self.total_fame: int = 0
        self.total_silver: int = 0
        self.events: deque = deque(maxlen=500)
        self.running: bool = False
        # Fenêtre glissante de 5 min pour le taux instantané
        self._window_events: deque = deque()

    def start(self):
        self.start_time = time.time()
        self.running = True

    def stop(self):
        self.running = False

    def add_fame(self, amount: int, source: str = ""):
        if not self.running or amount <= 0:
            return
        now = time.time()
        evt = StatEvent(timestamp=now, fame=amount, source=source)
        self.events.append(evt)
        self._window_events.append(evt)
        self.total_fame += amount
        self._prune_window()

    def add_silver(self, amount: int, source: str = ""):
        if not self.running or amount <= 0:
            return
        now = time.time()
        evt = StatEvent(timestamp=now, silver=amount, source=source)
        self.events.append(evt)
        self._window_events.append(evt)
        self.total_silver += amount
        self._prune_window()

    def _prune_window(self, window_seconds: float = 300.0):
        cutoff = time.time() - window_seconds
        while self._window_events and self._window_events[0].timestamp < cutoff:
            self._window_events.popleft()

    @property
    def elapsed_seconds(self) -> float:
        if not self.running or self.start_time == 0:
            return 0.0
        return time.time() - self.start_time

    @property
    def elapsed_str(self) -> str:
        s = int(self.elapsed_seconds)
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{sec:02d}"

    @property
    def fame_per_hour(self) -> float:
        elapsed = self.elapsed_seconds
        if elapsed < 1:
            return 0.0
        return self.total_fame / elapsed * 3600

    @property
    def silver_per_hour(self) -> float:
        elapsed = self.elapsed_seconds
        if elapsed < 1:
            return 0.0
        return self.total_silver / elapsed * 3600

    @property
    def instant_fame_per_hour(self) -> float:
        """Rate basé sur la fenêtre glissante de 5 min (plus réactif)."""
        self._prune_window()
        if not self._window_events:
            return 0.0
        elapsed = time.time() - self._window_events[0].timestamp
        if elapsed < 1:
            return 0.0
        fame_sum = sum(e.fame for e in self._window_events)
        return fame_sum / elapsed * 3600

    @property
    def instant_silver_per_hour(self) -> float:
        self._prune_window()
        if not self._window_events:
            return 0.0
        elapsed = time.time() - self._window_events[0].timestamp
        if elapsed < 1:
            return 0.0
        silver_sum = sum(e.silver for e in self._window_events)
        return silver_sum / elapsed * 3600

    def recent_events(self, n: int = 50) -> List[StatEvent]:
        return list(self.events)[-n:]
