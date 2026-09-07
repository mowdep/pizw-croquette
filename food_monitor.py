#!/usr/bin/env python3
"""Niveau de croquettes — HC-SR04 sur Raspberry Pi Zero WH.

Un seul thread mesure. Le web ne fait que lire l'état en cache.
Projet IoT local, sans authentification : tout se règle depuis l'interface,
identifiants MQTT/Telegram inclus, stockés dans config.json.
"""
from __future__ import annotations

import json
import logging
import os
import statistics
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt
import requests
from flask import Flask, jsonify, render_template, request

if os.getenv("FOOD_MONITOR_FAKE"):        # dev sans matériel : voir fakegpio.py
    import random

    from fakegpio import FakeHCSR04

    GPIO = FakeHCSR04(distances=lambda: random.uniform(4, 32))
else:
    import RPi.GPIO as GPIO

log = logging.getLogger("croquette")

CONFIG_PATH = Path(os.getenv("FOOD_MONITOR_CONFIG", "config.json"))

# DEFAULTS sert de schéma : il fixe les clés ET les types. Voir coerce().
# username/password/bot_token/chat_id vivent ici comme le reste : pas d'auth sur ce
# projet, réseau local uniquement — inutile de séparer un fichier de secrets.
DEFAULTS = {
    "sensor": {"trigger_pin": 23, "echo_pin": 24, "interval_s": 60, "samples": 5},
    "calibration": {"full_cm": 5.0, "empty_cm": 30.0},
    "mqtt": {"enabled": False, "host": "localhost", "port": 1883,
             "topic": "home/croquettes/level", "username": "", "password": ""},
    "telegram": {"enabled": False, "threshold_pct": 20, "cooldown_s": 3600,
                 "bot_token": "", "chat_id": ""},
    "web": {"host": "0.0.0.0", "port": 5000},
}

CREDENTIAL_FIELDS = (("mqtt", "username"), ("mqtt", "password"),
                     ("telegram", "bot_token"), ("telegram", "chat_id"))

SPEED_OF_SOUND_CM_S = 34300
RANGE_CM = (2.0, 400.0)          # hors de cette plage, le HC-SR04 raconte n'importe quoi
SETTLE_S = 0.06                  # >60 ms entre deux pings (datasheet)

CONFIG: dict = {}
STATE = {"level": None, "distance_cm": None, "measured_at": None, "mqtt_connected": False}
_gpio = threading.Lock()
_alert = {"active": False, "sent_at": 0.0}
_mqtt: mqtt.Client | None = None


# ---------------------------------------------------------------- configuration

def coerce(schema, value):
    """Aligne `value` sur la forme et les types de `schema`.

    Remplace à lui seul : le merge des défauts, la validation de types
    (les <input> HTML renvoient des strings) et le filtrage des clés inconnues.
    """
    if not isinstance(schema, dict):
        return bool(value) if isinstance(schema, bool) else type(schema)(value)
    if not isinstance(value, dict):
        value = {}
    return {k: coerce(v, value.get(k, v)) for k, v in schema.items()}


def validate(cfg: dict) -> None:
    cal, sensor, tg = cfg["calibration"], cfg["sensor"], cfg["telegram"]
    if not RANGE_CM[0] <= cal["full_cm"] < cal["empty_cm"] <= RANGE_CM[1]:
        raise ValueError("Calibration : distance « plein » < distance « vide », dans 2–400 cm.")
    if sensor["interval_s"] < 5:
        raise ValueError("Intervalle : 5 s minimum.")
    if not 1 <= sensor["samples"] <= 21:
        raise ValueError("Échantillons : entre 1 et 21.")
    if not 0 <= tg["threshold_pct"] <= 100:
        raise ValueError("Seuil d'alerte : entre 0 et 100 %.")
    if sensor["trigger_pin"] == sensor["echo_pin"]:
        raise ValueError("TRIG et ECHO doivent être sur deux broches différentes.")


def load_config() -> dict:
    try:
        raw = json.loads(CONFIG_PATH.read_text())
    except FileNotFoundError:
        raw = {}
    except json.JSONDecodeError as exc:
        log.error("config.json illisible (%s) — défauts appliqués.", exc)
        raw = {}
    cfg = coerce(DEFAULTS, raw)
    validate(cfg)
    return cfg


def save_config(cfg: dict) -> None:
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    tmp.chmod(0o600)          # contient les identifiants MQTT/Telegram en clair
    tmp.replace(CONFIG_PATH)  # écriture atomique : pas de config tronquée après coupure


def redact(cfg: dict) -> dict:
    """Config avec les identifiants réduits à un booléen : jamais renvoyés en clair sur le réseau."""
    out = json.loads(json.dumps(cfg))
    for section, key in CREDENTIAL_FIELDS:
        out[section][key] = bool(cfg[section][key])
    return out


# ---------------------------------------------------------------------- capteur

def _wait(pin: int, level: int, timeout: float) -> float | None:
    """Attend `level` sur `pin`. Renvoie l'instant, ou None au timeout."""
    deadline = time.monotonic() + timeout
    while GPIO.input(pin) != level:
        if time.monotonic() > deadline:
            return None
    return time.monotonic()


def _ping(trigger: int, echo: int) -> float | None:
    GPIO.output(trigger, True)
    time.sleep(10e-6)
    GPIO.output(trigger, False)
    start = _wait(echo, 1, 0.05)
    end = _wait(echo, 0, 0.05) if start else None
    return (end - start) * SPEED_OF_SOUND_CM_S / 2 if end else None


def measure(cfg: dict) -> float | None:
    """Médiane des mesures plausibles. None si le capteur ne répond pas."""
    s = cfg["sensor"]
    with _gpio:
        samples = []
        for _ in range(s["samples"]):
            d = _ping(s["trigger_pin"], s["echo_pin"])
            if d and RANGE_CM[0] <= d <= RANGE_CM[1]:
                samples.append(d)
            time.sleep(SETTLE_S)
    return round(statistics.median(samples), 1) if samples else None


def level_pct(distance: float | None, cal: dict) -> float | None:
    """0 % = vide, 100 % = plein. None si pas de mesure — surtout pas 0."""
    if distance is None:
        return None
    span = cal["empty_cm"] - cal["full_cm"]
    return round(min(100.0, max(0.0, (cal["empty_cm"] - distance) / span * 100)), 1)


# ------------------------------------------------------------------- sorties

def apply_mqtt(cfg: dict) -> None:
    global _mqtt
    if _mqtt:
        _mqtt.loop_stop()
        _mqtt.disconnect()
        _mqtt = None
    STATE["mqtt_connected"] = False
    if not cfg["mqtt"]["enabled"]:
        return
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)  # paho >= 2
    except AttributeError:
        client = mqtt.Client()                                  # paho 1.x
    if cfg["mqtt"]["username"]:
        client.username_pw_set(cfg["mqtt"]["username"], cfg["mqtt"]["password"])
    client.on_connect = lambda *_: STATE.update(mqtt_connected=True)
    client.on_disconnect = lambda *_: STATE.update(mqtt_connected=False)
    # connect_async : le démarrage ne dépend plus du broker, et paho reconnecte seul.
    client.connect_async(cfg["mqtt"]["host"], cfg["mqtt"]["port"], 60)
    client.loop_start()
    _mqtt = client


def publish(cfg: dict, level: float, distance: float) -> None:
    if not _mqtt:
        return
    payload = json.dumps({"level": level, "distance_cm": distance,
                          "timestamp": STATE["measured_at"]})
    _mqtt.publish(cfg["mqtt"]["topic"], payload, retain=True)


def telegram(tg: dict, text: str) -> None:
    try:
        requests.post(f"https://api.telegram.org/bot{tg['bot_token']}/sendMessage",
                      json={"chat_id": tg["chat_id"], "text": text}, timeout=10)
    except requests.RequestException as exc:
        log.warning("Telegram : %s", exc)


def notify(cfg: dict, level: float) -> None:
    """Alerte sur front descendant, avec hystérésis : pas de spam autour du seuil."""
    tg = cfg["telegram"]
    if not (tg["enabled"] and tg["bot_token"] and tg["chat_id"]):
        return
    now = time.monotonic()
    if level < tg["threshold_pct"]:
        if not _alert["active"] or now - _alert["sent_at"] > tg["cooldown_s"]:
            telegram(tg, f"Croquettes : {level} %. Il faut remplir.")
            _alert.update(active=True, sent_at=now)
    elif _alert["active"] and level >= tg["threshold_pct"] + 10:
        telegram(tg, f"Gamelle remplie : {level} %.")
        _alert["active"] = False


# ---------------------------------------------------------------------- boucle

def cycle() -> None:
    distance = measure(CONFIG)
    level = level_pct(distance, CONFIG["calibration"])
    if level is None:
        log.warning("Aucune mesure exploitable — état conservé, marqué obsolète.")
        return
    STATE.update(level=level, distance_cm=distance,
                 measured_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    publish(CONFIG, level, distance)
    notify(CONFIG, level)


def monitoring_loop() -> None:
    while True:
        try:
            cycle()
        except Exception:
            log.exception("Cycle de mesure en échec")
        time.sleep(CONFIG["sensor"]["interval_s"])


# ------------------------------------------------------------------------- web

app = Flask(__name__)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/status")
def api_status():
    return jsonify({**STATE, "config": redact(CONFIG)})


@app.post("/api/measure")
def api_measure():
    return jsonify(distance_cm=measure(CONFIG))


@app.post("/api/config")
def api_config():
    global CONFIG
    try:
        candidate = coerce(CONFIG, request.get_json(silent=True) or {})
        validate(candidate)
    except (ValueError, TypeError) as exc:
        return jsonify(error=str(exc)), 400
    mqtt_changed = candidate["mqtt"] != CONFIG["mqtt"]
    CONFIG = candidate
    save_config(CONFIG)
    if mqtt_changed:
        apply_mqtt(CONFIG)
    return jsonify(config=redact(CONFIG))


def main() -> None:
    global CONFIG
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    CONFIG = load_config()
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(CONFIG["sensor"]["trigger_pin"], GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(CONFIG["sensor"]["echo_pin"], GPIO.IN)
    apply_mqtt(CONFIG)
    threading.Thread(target=monitoring_loop, daemon=True).start()
    try:
        app.run(host=CONFIG["web"]["host"], port=CONFIG["web"]["port"], debug=False)
    finally:
        if _mqtt:
            _mqtt.loop_stop()
        GPIO.cleanup()


if __name__ == "__main__":
    main()
