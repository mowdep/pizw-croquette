# pizw-croquette

Niveau de croquettes mesuré par HC-SR04 sur Raspberry Pi Zero WH. Interface web,
publication MQTT, alerte Telegram.

Un seul thread interroge le capteur ; le web sert un cache. Projet IoT local,
sans authentification : tout se règle depuis l'interface, identifiants
MQTT/Telegram inclus.

## Câblage

Voir [WIRING.md](WIRING.md). **À lire avant de brancher** : un module régulateur
AMS1117 ne peut pas servir d'adaptateur de niveau pour ECHO.

## Installation

```bash
sudo useradd -r -G gpio -d /opt/pizw-croquette croquette
sudo git clone -b refonte/hcsr04 \
     https://github.com/mowdep/pizw-croquette /opt/pizw-croquette
cd /opt/pizw-croquette

python3 -m venv .venv                      # PEP 668 : pip refuse le système
.venv/bin/pip install -r requirements.txt

cp config.example.json config.json
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

Interface sur `http://<ip-du-pi>:5000`. Pas d'authentification : quiconque sur le
réseau local peut lire et modifier les réglages — cohérent pour un projet IoT
personnel, pas à exposer tel quel sur Internet.

## Calibration

Interface → Calibrer. Trémie vide, mesurer. Trémie pleine, mesurer. Le capteur
voit la surface des croquettes : plus elles sont hautes, plus la distance est courte.

## Configuration

`config.json` contient tous les réglages, identifiants MQTT/Telegram compris, et
se modifie depuis l'interface. Les clés absentes reprennent leur valeur par
défaut, les clés inconnues sont ignorées, les types sont convertis. Le fichier
est écrit en 0600 (identifiants en clair dedans) et jamais commité (`.gitignore`).

Utilisateur/mot de passe MQTT vides = connexion anonyme. Jeton bot et
identifiant de chat Telegram vides = alertes désactivées même si `enabled: true`.

`FOOD_MONITOR_FAKE=1` : capteur simulé, pour développer sans Pi.

## API

| Route | |
|---|---|
| `GET /api/status` | Niveau, distance, horodatage **de la mesure**, état MQTT, config (identifiants réduits à un booléen) |
| `POST /api/config` | Patch partiel, validé en bloc. Un champ identifiant laissé vide dans l'UI n'écrase pas la valeur existante. |
| `POST /api/measure` | Une mesure immédiate, pour la calibration. |

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
