#!/usr/bin/env python3
"""Suite de tests — aucun matériel requis.

    python3 test_food_monitor.py          (ou : python3 -m pytest test_food_monitor.py -v)

Couvre la chaîne complète : protocole HC-SR04 simulé à la microseconde,
filtrage, calibration, API, secrets, concurrence GPIO. À faire tourner sur le
poste de dev avant tout déploiement. Sur le Pi, enchaîner avec preflight.py,
qui teste le vrai capteur et le vrai câblage.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
import threading

os.environ.setdefault("FOOD_MONITOR_FAKE", "1")
os.environ["FOOD_MONITOR_CONFIG"] = os.path.join(tempfile.mkdtemp(), "config.json")

import food_monitor as fm                       # noqa: E402
from fakegpio import FakeHCSR04, VirtualClock   # noqa: E402


@contextlib.contextmanager
def sensor(**kwargs):
    """Branche un capteur simulé sur une horloge virtuelle : déterministe et instantané."""
    clock = VirtualClock()
    fake = FakeHCSR04(clock=clock, **kwargs)
    real_gpio, real_time = fm.GPIO, fm.time
    fm.GPIO, fm.time = fake, clock
    try:
        yield fake
    finally:
        fm.GPIO, fm.time = real_gpio, real_time


def cfg(**patch):
    return fm.coerce(fm.DEFAULTS, patch)


# ------------------------------------------------------------------ capteur

def test_ping_mesure_la_bonne_distance():
    """58 µs par centimètre : le chronométrage doit tenir la résolution."""
    for expected in (2.5, 15.0, 100.0, 399.0):
        with sensor(distances=expected):
            got = fm.measure(cfg(sensor={"samples": 1}))
        assert got is not None and abs(got - expected) < 0.2, f"{expected} cm → {got} cm"


def test_capteur_muet_renvoie_none():
    """Pas d'écho : None, jamais 0. Une gamelle inconnue n'est pas une gamelle vide."""
    with sensor(mute=True):
        assert fm.measure(cfg()) is None


def test_echo_bloque_haut_ne_bloque_pas_la_boucle():
    """ECHO collé à 1 (branché en direct sur 5 V, capteur mort) : timeout, pas de blocage."""
    with sensor(distances=1e6):
        assert fm.measure(cfg(sensor={"samples": 1})) is None


def test_mediane_absorbe_les_valeurs_aberrantes():
    """Le HC-SR04 sort régulièrement une valeur fantaisiste. Elle ne doit pas passer."""
    with sensor(distances=[15.0, 15.2, 250.0, 14.9, 15.1]):
        got = fm.measure(cfg(sensor={"samples": 5}))
    assert abs(got - 15.1) < 0.3, got


def test_hors_plage_rejete():
    """Au-delà de 400 cm le capteur ment : on jette avant de calculer la médiane."""
    with sensor(distances=[15.0, 450.0, 15.0]):
        assert abs(fm.measure(cfg(sensor={"samples": 3})) - 15.0) < 0.3
    with sensor(distances=450.0):
        assert fm.measure(cfg(sensor={"samples": 3})) is None


def test_verrou_gpio_tient_sous_concurrence():
    """Régression du bloquant nº 4 : le simulateur lève si deux pings se chevauchent.

    Écho long (350 cm ≈ 20 ms) et commutation de threads agressive, pour que
    l'absence de verrou se manifeste à coup sûr au lieu de dépendre du GIL.
    """
    fake = FakeHCSR04(distances=350.0)      # horloge réelle : vrai parallélisme
    real, fm.GPIO = fm.GPIO, fake
    switch = sys.getswitchinterval()
    sys.setswitchinterval(1e-4)
    resultats = []

    def mesurer():
        try:
            resultats.append(fm.measure(cfg(sensor={"samples": 2})))
        except RuntimeError as exc:
            resultats.append(exc)

    try:
        threads = [threading.Thread(target=mesurer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        fm.GPIO = real
        sys.setswitchinterval(switch)
    assert len(resultats) == 4 and all(isinstance(r, float) for r in resultats), resultats


def test_http_ne_declenche_aucune_mesure():
    """Régression : /api/level pilotait le GPIO à chaque GET. /api/status lit un cache."""
    fm.CONFIG = fm.load_config()
    with sensor() as fake:
        client = fm.app.test_client()
        for _ in range(5):
            client.get("/api/status")
        assert fake.pings == 0


# ------------------------------------------------------------ configuration

def test_coerce_types_defauts_et_cles_inconnues():
    got = fm.coerce(fm.DEFAULTS, {"sensor": {"interval_s": "90"},   # <input> → string
                                  "telegram": {"enabled": "on"},
                                  "inconnu": {"x": 1}})             # rejetée
    assert got["sensor"]["interval_s"] == 90 and isinstance(got["sensor"]["interval_s"], int)
    assert got["telegram"]["enabled"] is True
    assert got["sensor"]["trigger_pin"] == 23                       # clé absente → défaut
    assert "inconnu" not in got


def test_config_illisible_ne_bloque_pas_le_demarrage():
    fm.CONFIG_PATH.write_text("{ ceci n'est pas du JSON")
    try:
        assert fm.load_config() == fm.DEFAULTS
    finally:
        fm.CONFIG_PATH.unlink()


def test_ecriture_atomique():
    fm.save_config(cfg(calibration={"empty_cm": 42.0}))
    assert json.loads(fm.CONFIG_PATH.read_text())["calibration"]["empty_cm"] == 42.0
    assert not fm.CONFIG_PATH.with_suffix(".tmp").exists()


def test_validate_rejette_les_configs_impossibles():
    for bad in ({"calibration": {"full_cm": 30.0, "empty_cm": 5.0}},   # inversée
                {"calibration": {"full_cm": 10.0, "empty_cm": 10.0}},  # division par zéro
                {"calibration": {"full_cm": 0.5, "empty_cm": 20.0}},   # sous la portée mini
                {"sensor": {"interval_s": 0}},
                {"sensor": {"samples": 0}},
                {"sensor": {"trigger_pin": 24, "echo_pin": 24}},
                {"telegram": {"threshold_pct": 150}}):
        try:
            fm.validate(cfg(**bad))
        except ValueError:
            continue
        raise AssertionError(f"config invalide acceptée : {bad}")


# -------------------------------------------------------------- calibration

def test_level_pct():
    cal = {"full_cm": 5.0, "empty_cm": 30.0}
    assert [fm.level_pct(d, cal) for d in (5, 17.5, 30, 1, 99)] == [100.0, 50.0, 0.0, 100.0, 0.0]
    assert fm.level_pct(None, cal) is None


# ------------------------------------------------------------ notifications

def test_notify_hysteresis():
    """Une alerte, un retour à la normale, une alerte. Pas un message par cycle."""
    envoyes = []
    reel, fm.telegram = fm.telegram, lambda tg, text: envoyes.append(text)
    fm._alert.update(active=False, sent_at=0.0)
    try:
        for level in (50, 19, 18, 15, 22, 35, 10):
            fm.notify(cfg(telegram={"enabled": True, "threshold_pct": 20,
                                     "bot_token": "x", "chat_id": "y"}), level)
    finally:
        fm.telegram = reel
    assert len(envoyes) == 3, envoyes
    assert "22" not in "".join(envoyes)     # 22 % est dans la bande morte : silence


def test_notify_muet_sans_secret():
    envoyes = []
    reel, fm.telegram = fm.telegram, lambda tg, text: envoyes.append(text)
    fm._alert.update(active=False, sent_at=0.0)
    try:
        fm.notify(cfg(telegram={"enabled": True, "threshold_pct": 20}), 5)  # bot_token/chat_id vides
    finally:
        fm.telegram = reel
    assert envoyes == []


# --------------------------------------------------------------------- MQTT

def test_publish_payload():
    publie = []
    fm._mqtt = type("Faux", (), {"publish": lambda s, t, p, retain: publie.append((t, p))})()
    fm.STATE["measured_at"] = "2026-08-24T10:00:00+00:00"
    try:
        fm.publish(cfg(mqtt={"topic": "maison/croquettes"}), 42.0, 19.5)
    finally:
        fm._mqtt = None
    topic, payload = publie[0]
    assert topic == "maison/croquettes"
    assert json.loads(payload) == {"level": 42.0, "distance_cm": 19.5,
                                   "timestamp": "2026-08-24T10:00:00+00:00"}


def test_publish_sans_broker_ne_leve_pas():
    fm._mqtt = None
    fm.publish(cfg(), 42.0, 19.5)


# ---------------------------------------------------------------------- API

def test_api_etat_initial_et_absence_de_secrets():
    """Pas d'auth sur ce projet, mais les identifiants ne doivent jamais transiter en clair."""
    fm.CONFIG = fm.coerce(fm.DEFAULTS, {"mqtt": {"username": "gabriel-user", "password": "s3cr3t-pass"},
                                        "telegram": {"bot_token": "999:BOTTOKEN", "chat_id": "chat-id-777"}})
    fm.STATE.update(level=None, distance_cm=None, measured_at=None)
    corps = fm.app.test_client().get("/api/status").get_json()
    assert corps["level"] is None and corps["measured_at"] is None
    for secret in ("gabriel-user", "s3cr3t-pass", "999:BOTTOKEN", "chat-id-777"):
        assert secret not in json.dumps(corps)
    assert corps["config"]["mqtt"]["username"] is True     # présence, jamais la valeur
    assert corps["config"]["telegram"]["bot_token"] is True


def test_api_config_valide_et_persiste():
    fm.CONFIG = fm.load_config()
    client = fm.app.test_client()
    assert client.post("/api/config", json={"calibration": {"empty_cm": 40}}).status_code == 200
    assert json.loads(fm.CONFIG_PATH.read_text())["calibration"]["empty_cm"] == 40.0
    r = client.post("/api/config", json={"calibration": {"full_cm": 99}})
    assert r.status_code == 400 and "Calibration" in r.get_json()["error"]
    assert fm.CONFIG["calibration"]["full_cm"] == 5.0        # rien n'a bougé


def test_api_config_supporte_les_strings_du_navigateur():
    fm.CONFIG = fm.load_config()
    r = fm.app.test_client().post("/api/config", json={"sensor": {"interval_s": "120"}})
    assert r.status_code == 200 and fm.CONFIG["sensor"]["interval_s"] == 120


def test_api_config_champ_identifiant_omis_ne_l_efface_pas():
    """L'UI ne renvoie jamais un champ identifiant laissé vide : l'omission doit préserver."""
    fm.CONFIG = fm.coerce(fm.DEFAULTS, {"mqtt": {"username": "gabriel-user", "password": "s3cr3t-pass"}})
    client = fm.app.test_client()
    r = client.post("/api/config", json={"mqtt": {"host": "192.168.1.50"}})
    assert r.status_code == 200
    assert fm.CONFIG["mqtt"]["host"] == "192.168.1.50"
    assert fm.CONFIG["mqtt"]["username"] == "gabriel-user"   # pas dans le patch : inchangé
    assert r.get_json()["config"]["mqtt"]["password"] is True  # jamais réaffiché en clair


def test_page_html_se_rend():
    assert b"Croquettes" in fm.app.test_client().get("/").data


def test_cycle_complet():
    fm.CONFIG = fm.load_config()
    with sensor(distances=17.5):
        fm.cycle()
    assert fm.STATE["measured_at"] and abs(fm.STATE["level"] - 50.0) < 1
    assert abs(fm.STATE["distance_cm"] - 17.5) < 0.2


def test_cycle_sur_capteur_muet_conserve_la_derniere_valeur():
    """L'horodatage doit rester celui de la mesure : c'est ce qui rend la panne visible."""
    fm.CONFIG = fm.load_config()
    with sensor(distances=17.5):
        fm.cycle()
    horodatage = fm.STATE["measured_at"]
    with sensor(mute=True):
        fm.cycle()
    assert fm.STATE["measured_at"] == horodatage


if __name__ == "__main__":
    cas = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for nom, fonction in cas:
        fonction()
        print(f"  ok  {nom}")
    print(f"\n{len(cas)} tests passés.")
