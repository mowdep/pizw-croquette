#!/usr/bin/env python3
"""Préflight — à lancer SUR le Raspberry Pi, avant d'activer le service.

    python3 preflight.py

Vérifie l'environnement, les permissions, puis interroge réellement le capteur
et diagnostique le câblage. Sort en code 1 si quelque chose bloque.

Les tests de test_food_monitor.py valident la logique sans matériel ;
celui-ci valide le matériel.
"""
from __future__ import annotations

import grp
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

VERT, JAUNE, ROUGE, GRIS, RAZ = "\033[32m", "\033[33m", "\033[31m", "\033[90m", "\033[0m"
if not sys.stdout.isatty():
    VERT = JAUNE = ROUGE = GRIS = RAZ = ""

problemes, avertissements = [], []


def ok(titre, detail=""):
    print(f"{VERT}  ok  {RAZ}{titre}{GRIS}{'  ' + detail if detail else ''}{RAZ}")


def warn(titre, detail=""):
    avertissements.append(titre)
    print(f"{JAUNE} attn {RAZ}{titre}")
    if detail:
        print(f"       {GRIS}{detail}{RAZ}")


def fail(titre, detail=""):
    problemes.append(titre)
    print(f"{ROUGE} STOP {RAZ}{titre}")
    if detail:
        print(f"       {detail}")


def titre(texte):
    print(f"\n{texte}")


# ---------------------------------------------------------------- environnement

def check_python():
    if sys.version_info < (3, 9):
        fail(f"Python {sys.version_info.major}.{sys.version_info.minor}",
             "Il faut 3.9 minimum. Raspberry Pi OS Bookworm fournit 3.11.")
    else:
        ok(f"Python {sys.version_info.major}.{sys.version_info.minor}")


def check_imports():
    """Le test qui aurait évité tout ce qui suit : est-ce que ça s'importe ?"""
    modules = ["flask", "paho.mqtt.client", "requests"]
    if not os.getenv("FOOD_MONITOR_FAKE"):
        modules.append("RPi.GPIO")
    for module in modules:
        try:
            __import__(module)
            ok(f"import {module}")
        except ImportError as exc:
            fail(f"import {module}", str(exc))


def check_gpio_access():
    for chemin in ("/dev/gpiomem", "/dev/gpiochip0"):
        if Path(chemin).exists():
            if os.access(chemin, os.R_OK | os.W_OK):
                ok(f"accès {chemin}")
            else:
                groupes = [grp.getgrgid(g).gr_name for g in os.getgroups()]
                fail(f"accès {chemin} refusé",
                     f"Groupes actuels : {', '.join(groupes)}.\n"
                     f"       sudo usermod -aG gpio $USER  puis rouvrir la session.")
            return
    fail("aucun périphérique GPIO", "Ce n'est pas un Raspberry Pi, ou le noyau est inhabituel.")


def check_modele():
    try:
        modele = Path("/proc/device-tree/model").read_text().strip("\x00")
    except OSError:
        warn("modèle indéterminé", "Le préflight suppose un Raspberry Pi.")
        return
    ok(modele)
    if "Pi 5" in modele:
        warn("RPi.GPIO ne fonctionne pas sur Pi 5",
             "Passer à gpiozero + lgpio, ou rester sur un Pi antérieur.")


def check_broches_libres(cfg):
    """I2C, SPI et UART squattent certaines broches ; un conflit est silencieux."""
    reserves = {2: "I2C SDA", 3: "I2C SCL", 14: "UART TX", 15: "UART RX",
                7: "SPI CE1", 8: "SPI CE0", 9: "SPI MISO", 10: "SPI MOSI", 11: "SPI SCLK"}
    actifs = set()
    for nom, fichier in (("i2c", "/dev/i2c-1"), ("spi", "/dev/spidev0.0")):
        if Path(fichier).exists():
            actifs.add(nom)
    for role in ("trigger_pin", "echo_pin"):
        broche = cfg["sensor"][role]
        usage = reserves.get(broche)
        if usage and (("I2C" in usage and "i2c" in actifs) or ("SPI" in usage and "spi" in actifs)):
            fail(f"{role} = GPIO {broche}", f"Broche occupée par {usage}, actuellement activé.")
        elif usage:
            warn(f"{role} = GPIO {broche}", f"Broche partagée avec {usage} (désactivé pour l'instant).")
        else:
            ok(f"{role} = GPIO {broche}")


# ------------------------------------------------------------------ secrets

def check_secrets(cfg):
    cfgpath = Path("config.json")
    if cfgpath.exists():
        mode = cfgpath.stat().st_mode & 0o777
        (ok if mode == 0o600 else warn)(
            f"config.json en {oct(mode)}",
            "" if mode == 0o600 else "chmod 600 config.json — identifiants MQTT/Telegram en clair dedans.")
    if cfg["telegram"]["enabled"] and not (cfg["telegram"]["bot_token"] and cfg["telegram"]["chat_id"]):
        fail("Telegram activé sans identifiants",
             "Renseigner le jeton du bot et l'identifiant de chat depuis l'interface web.")


# ------------------------------------------------------------------ capteur

def diagnostic_echo(fm, cfg) -> bool:
    """Distingue les pannes de câblage par leur signature électrique."""
    echo, trig = cfg["sensor"]["echo_pin"], cfg["sensor"]["trigger_pin"]

    hauts = sum(fm.GPIO.input(echo) for _ in range(200))     # ECHO au repos, sans trigger
    if hauts > 190:
        fail("ECHO reste à l'état haut en permanence",
             "La broche voit une tension continue, pas un signal.\n"
             "       Signature typique d'un régulateur (AMS1117) inséré sur la ligne ECHO :\n"
             "       un régulateur est une alimentation, il ne transmet pas d'impulsion.\n"
             "       Utiliser un pont diviseur : ECHO --[1k]--+--[1.8k]-- GND, GPIO sur le point milieu.")
        return False
    if hauts > 5:
        warn(f"ECHO instable au repos ({hauts}/200 lectures hautes)",
             "Masse commune absente, fils trop longs, ou capteur qui parle tout seul.")

    fm.GPIO.output(trig, True)
    time.sleep(10e-6)
    fm.GPIO.output(trig, False)
    if fm._wait(echo, 1, 0.05) is None:
        fail("aucun écho après impulsion sur TRIG",
             "Vérifier : VCC du capteur sur 5 V (pin 2), GND commun (pin 6),\n"
             "       TRIG et ECHO non inversés, et le capteur bien alimenté.")
        return False
    if fm._wait(echo, 0, 0.05) is None:
        fail("ECHO monte mais ne redescend pas",
             "Cible hors de portée (> 4 m), ou signal filtré par un condensateur\n"
             "       sur la ligne — encore la signature d'un module régulateur.")
        return False
    ok("protocole TRIG/ECHO fonctionnel")
    return True


def mesures(fm, cfg, n=20):
    brutes, echecs = [], 0
    for _ in range(n):
        d = fm._ping(cfg["sensor"]["trigger_pin"], cfg["sensor"]["echo_pin"])
        if d is None or not fm.RANGE_CM[0] <= d <= fm.RANGE_CM[1]:
            echecs += 1
        else:
            brutes.append(d)
        time.sleep(fm.SETTLE_S)
    return brutes, echecs


def check_capteur(fm, cfg):
    if not diagnostic_echo(fm, cfg):
        return None
    print(f"{GRIS}       20 mesures en cours…{RAZ}")
    brutes, echecs = mesures(fm, cfg)
    taux = echecs / 20
    if not brutes:
        fail("aucune mesure exploitable sur 20")
        return None
    ecart = statistics.stdev(brutes) if len(brutes) > 1 else 0.0
    mediane = statistics.median(brutes)
    detail = (f"médiane {mediane:.1f} cm · "
              f"min {min(brutes):.1f} · max {max(brutes):.1f} · "
              f"écart-type {ecart:.2f} cm · {echecs}/20 échecs")
    if taux > 0.2:
        fail("capteur peu fiable", detail + "\n       Plus de 20 % d'échecs : alimentation "
             "insuffisante, masse mal reliée, ou niveau logique limite.")
    elif taux > 0.05 or ecart > 1.0:
        warn("mesures dispersées", detail + "\n       Capteur mal fixé, surface des croquettes "
             "irrégulière, ou pont diviseur mal dimensionné.")
    else:
        ok("capteur stable", detail)
    return mediane


def check_calibration(fm, cfg, mediane):
    if mediane is None:
        return
    cal = cfg["calibration"]
    niveau = fm.level_pct(mediane, cal)
    if not cal["full_cm"] - 2 <= mediane <= cal["empty_cm"] + 2:
        warn(f"{mediane:.1f} cm hors de la plage calibrée "
             f"({cal['full_cm']}–{cal['empty_cm']} cm)",
             "Recalibrer depuis l'interface avant de se fier au pourcentage.")
    else:
        ok(f"niveau calculé : {niveau} %")


# -------------------------------------------------------------------- réseau

def check_mqtt(cfg):
    if not cfg["mqtt"]["enabled"]:
        return
    import paho.mqtt.client as mqtt
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()
    if cfg["mqtt"]["username"]:
        client.username_pw_set(cfg["mqtt"]["username"], cfg["mqtt"]["password"])
    try:
        client.connect(cfg["mqtt"]["host"], cfg["mqtt"]["port"], 5)
        client.disconnect()
        ok(f"broker MQTT {cfg['mqtt']['host']}:{cfg['mqtt']['port']}")
    except OSError as exc:
        fail(f"broker MQTT injoignable : {exc}")


def check_telegram(cfg):
    if not (cfg["telegram"]["enabled"] and cfg["telegram"]["bot_token"]):
        return
    import requests
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{cfg['telegram']['bot_token']}/getMe", timeout=10)
        corps = r.json()
        if corps.get("ok"):
            ok(f"bot Telegram @{corps['result']['username']}")
        else:
            fail("jeton Telegram refusé")
    except requests.RequestException as exc:
        fail(f"API Telegram injoignable : {exc}")


def check_service():
    unite = Path("/etc/systemd/system/food-monitor.service")
    if not unite.exists():
        return
    try:
        actif = subprocess.run(["systemctl", "is-active", "food-monitor"],
                               capture_output=True, text=True).stdout.strip()
    except FileNotFoundError:
        return
    if actif == "active":
        warn("le service tourne déjà",
             "Il détient le GPIO : les mesures ci-dessus peuvent être faussées.\n"
             "       sudo systemctl stop food-monitor  puis relancer ce préflight.")


# ---------------------------------------------------------------------- main

def main() -> int:
    simule = bool(os.getenv("FOOD_MONITOR_FAKE"))
    print(f"Préflight — {'CAPTEUR SIMULÉ' if simule else 'matériel réel'}")

    titre("Environnement")
    check_python()
    check_imports()
    if not simule:
        check_modele()
        check_gpio_access()
        check_service()

    if problemes:
        print(f"\n{ROUGE}Arrêt : l'environnement n'est pas prêt.{RAZ}")
        return 1

    import food_monitor as fm
    try:
        cfg = fm.load_config()
    except (ValueError, json.JSONDecodeError) as exc:
        fail(f"config.json invalide : {exc}")
        return 1
    ok(f"config chargée depuis {fm.CONFIG_PATH}")

    titre("Câblage")
    check_broches_libres(cfg)
    fm.GPIO.setmode(fm.GPIO.BCM)
    fm.GPIO.setup(cfg["sensor"]["trigger_pin"], fm.GPIO.OUT, initial=fm.GPIO.LOW)
    fm.GPIO.setup(cfg["sensor"]["echo_pin"], fm.GPIO.IN)
    try:
        titre("Capteur")
        mediane = check_capteur(fm, cfg)
        check_calibration(fm, cfg, mediane)
    finally:
        fm.GPIO.cleanup()

    titre("Secrets et réseau")
    check_secrets(cfg)
    check_mqtt(cfg)
    check_telegram(cfg)

    print()
    if problemes:
        print(f"{ROUGE}{len(problemes)} blocage(s). Ne pas déployer.{RAZ}")
        return 1
    if avertissements:
        print(f"{JAUNE}{len(avertissements)} avertissement(s). Déploiement possible, "
              f"à surveiller.{RAZ}")
        return 0
    print(f"{VERT}Tout est vert. sudo systemctl enable --now food-monitor{RAZ}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
