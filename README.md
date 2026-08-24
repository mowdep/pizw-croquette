# pizw-croquette

Niveau de croquettes mesuré par HC-SR04 sur Raspberry Pi Zero WH. Interface web,
publication MQTT, alerte Telegram.

Un seul thread interroge le capteur ; le web sert un cache. Les secrets vivent
dans l'environnement, jamais dans un fichier de l'application.

## Câblage

Voir [WIRING.md](WIRING.md). **À lire avant de brancher** : un module régulateur
AMS1117 ne peut pas servir d'adaptateur de niveau pour ECHO.

## Installation

```bash
sudo useradd -r -G gpio -d /opt/pizw-croquette croquette
sudo git clone -b copilot/add-hcsr04-food-dispenser \
     https://github.com/mowdep/pizw-croquette /opt/pizw-croquette
cd /opt/pizw-croquette

python3 -m venv .venv                      # PEP 668 : pip refuse le système
.venv/bin/pip install -r requirements.txt

cp config.example.json config.json
cp env.example .env && chmod 600 .env      # y mettre au moins FOOD_MONITOR_TOKEN
```

## Vérifier avant de déployer

```bash
python3 test_food_monitor.py    # 23 tests, aucun matériel requis, < 1 s
python3 preflight.py            # sur le Pi : permissions, câblage, capteur, réseau
```

`preflight.py` prend 20 mesures réelles et donne un verdict sur le montage —
écart-type, taux d'échec, et un diagnostic nommé pour chaque panne de câblage
courante. Il sort en code 1 si quelque chose bloque.

## Déployer

```bash
sudo cp food-monitor.service /etc/systemd/system/
sudo systemctl enable --now food-monitor
journalctl -u food-monitor -f
```

Interface sur `http://<ip-du-pi>:5000`. Avec un jeton configuré, l'ouvrir avec
`?token=...` pour pouvoir modifier les réglages ; sans jeton, la lecture reste libre.

## Calibration

Interface → Calibrer. Trémie vide, mesurer. Trémie pleine, mesurer. Le capteur
voit la surface des croquettes : plus elles sont hautes, plus la distance est courte.

## Configuration

`config.json` contient uniquement des réglages non sensibles ; il est modifiable
depuis l'interface. Les clés absentes reprennent leur valeur par défaut, les clés
inconnues sont ignorées, les types sont convertis.

Les secrets passent par `.env`, chargé par systemd (`EnvironmentFile`) :

| Variable | Rôle |
|---|---|
| `FOOD_MONITOR_TOKEN` | Requis pour écrire la config. Absent = tout le LAN peut écrire. |
| `MQTT_USERNAME`, `MQTT_PASSWORD` | Broker, si authentifié |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Alertes |
| `FOOD_MONITOR_FAKE=1` | Capteur simulé, pour développer sans Pi |

## API

| Route | |
|---|---|
| `GET /api/status` | Niveau, distance, horodatage **de la mesure**, état MQTT, config |
| `POST /api/config` | Patch partiel, validé en bloc. Jeton requis. |
| `POST /api/measure` | Une mesure immédiate, pour la calibration. Jeton requis. |

`level` vaut `null` quand aucune mesure valide n'est disponible — jamais 0.
`measured_at` date la mesure, pas la requête : c'est ce qui rend une panne de
capteur visible dans l'interface.

MQTT publie sur le sujet configuré, avec `retain` :

```json
{"level": 42.0, "distance_cm": 19.5, "timestamp": "2026-08-24T10:00:00+00:00"}
```

## Développement

```bash
FOOD_MONITOR_FAKE=1 python3 food_monitor.py
```

`fakegpio.py` simule le protocole TRIG/ECHO complet, pas juste des valeurs
aléatoires : la chaîne de mesure est donc réellement testée.
