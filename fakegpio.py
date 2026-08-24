"""HC-SR04 simulé — teste toute la chaîne de mesure sans Raspberry Pi.

Sert aux tests (avec `VirtualClock`, déterministe et instantané) et au
développement de l'interface sur un poste sans matériel (`FOOD_MONITOR_FAKE=1`).

Le simulateur reproduit le protocole réel : impulsion sur TRIG, puis ECHO à
l'état haut pendant 2·d/34300 secondes. Les fonctions `_wait`, `_ping` et
`measure` sont donc exercées telles quelles, pas court-circuitées.
"""
from __future__ import annotations

import time

SPEED_OF_SOUND_CM_S = 34300


class VirtualClock:
    """Horloge déterministe. Chaque lecture avance d'un pas, comme une boucle réelle."""

    def __init__(self, step: float = 1e-6):
        self.t = 0.0
        self.step = step

    def monotonic(self) -> float:
        self.t += self.step
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


class FakeHCSR04:
    """Remplace le module RPi.GPIO.

    distances : nombre fixe, liste parcourue en boucle, ou fonction sans argument.
    mute      : le capteur ne répond jamais (débranché, hors portée).
    """

    BCM = OUT = LOW = 0
    IN = HIGH = 1

    def __init__(self, distances=15.0, clock=time, echo_delay_s: float = 5e-4,
                 mute: bool = False):
        self.clock = clock
        self.echo_delay_s = echo_delay_s
        self.mute = mute
        self.distances = distances
        self.pings = 0
        self._index = 0
        self._trig_high = False
        self._echo = (0.0, 0.0)      # fenêtre pendant laquelle ECHO est haut
        self._busy_until = 0.0       # fin de l'écho attendu : sert à détecter les collisions

    # --- API RPi.GPIO ---------------------------------------------------
    def setmode(self, *a, **k) -> None: pass
    def setup(self, *a, **k) -> None: pass
    def cleanup(self, *a, **k) -> None: pass

    def output(self, pin: int, value) -> None:
        if value and not self._trig_high:
            if self.clock.monotonic() < self._busy_until:
                raise RuntimeError(
                    "Deux mesures simultanées : un écho est encore en vol. "
                    "Le verrou GPIO ne tient pas.")
            self._trig_high = True
        elif self._trig_high and not value:      # front descendant : le capteur part
            self._trig_high = False
            self.pings += 1
            if self.mute:
                self._echo = (float("inf"), float("inf"))
                return
            start = self.clock.monotonic() + self.echo_delay_s
            self._echo = (start, start + 2 * self._next() / SPEED_OF_SOUND_CM_S)
            self._busy_until = self._echo[1]

    def input(self, pin: int) -> int:
        return int(self._echo[0] <= self.clock.monotonic() < self._echo[1])

    # --- interne --------------------------------------------------------
    def _next(self) -> float:
        if callable(self.distances):
            return float(self.distances())
        if isinstance(self.distances, (list, tuple)):
            value = self.distances[self._index % len(self.distances)]
            self._index += 1
            return float(value)
        return float(self.distances)
