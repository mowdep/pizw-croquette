# Câblage — Pi Zero WH + HC-SR04

## Le module AMS1117 acheté ne convient pas pour ECHO

Un module « 4,75–12 V → 3,3 V 800 mA » à base d'AMS1117 est un **régulateur
d'alimentation**, pas un adaptateur de niveau logique. Sur la ligne ECHO il ne
marchera pas, pour trois raisons :

- Un régulateur maintient sa sortie à 3,3 V *quoi qu'il arrive en entrée*. C'est
  exactement le contraire de ce qu'on veut : ici, il faut que la sortie recopie
  l'entrée, en la divisant.
- Ses condensateurs de sortie (10 à 100 µF) lissent tout. L'impulsion ECHO dure
  150 µs à 25 ms et sa mesure repose sur la position de ses fronts à la
  microseconde près. Un condensateur de 10 µF chargé par une entrée GPIO qui
  consomme quelques µA met plusieurs secondes à se décharger.
- L'AMS1117 ne peut pas *tirer* de courant vers la masse. Une fois sa sortie à
  3,3 V, rien ne la fait redescendre.

Résultat concret : GPIO 24 reste bloqué à 3,3 V, `_wait(echo, 0)` expire à chaque
cycle, aucune mesure ne sort. Aucun risque pour le Pi, mais aucune mesure non plus.
`preflight.py` détecte précisément cette signature et le dit.

Garde le module pour un autre projet — le Pi fournit déjà du 3,3 V régulé sur les
pins 1 et 17.

## Ce qu'il faut : deux résistances

```
HC-SR04 ECHO ──[ 1 kΩ ]──┬── GPIO 24  (pin 18)
                         │
                      [ 1,8 kΩ ]
                         │
                        GND
```

5 V × 1,8 / (1 + 1,8) = **3,21 V**, sous les 3,3 V du rail, avec un peu de marge.

Le 1 kΩ / 2 kΩ que recommandait l'ancienne doc donne 3,33 V : ça fonctionne, tout
le monde le fait, mais c'est 30 mV au-dessus du rail et la diode de protection du
GPIO conduit légèrement. 1,8 kΩ coûte pareil.

Autres paires valides (rapport ≈ 1 : 1,8) : 10 kΩ / 18 kΩ (moins de courant,
0,18 mA), 4,7 kΩ / 8,2 kΩ, 2,2 kΩ / 3,9 kΩ. Éviter au-delà de 47 kΩ : la constante
de temps avec la capacité parasite finit par arrondir les fronts.

## Test à coût nul, avant d'acheter quoi que ce soit

Beaucoup de HC-SR04 du commerce (et tous les HC-SR04P / RCWL-1601) fonctionnent
sous 3,3 V. Dans ce cas ECHO sort à 3,3 V et **aucune adaptation n'est nécessaire** :

```
VCC  → pin 1  (3,3 V)      au lieu de pin 2
TRIG → pin 16 (GPIO 23)
ECHO → pin 18 (GPIO 24)    en direct
GND  → pin 6
```

Puis `python3 preflight.py`. S'il affiche « capteur stable » avec un écart-type
sous 0,5 cm et 0 échec sur 20, c'est bon : la trémie fait 30 cm, on est très
en dessous de la portée où le sous-voltage pose problème. Sinon, commande les
deux résistances.

> **Jamais** VCC sur 5 V *et* ECHO en direct sur le GPIO. Les entrées du BCM2835
> ne tolèrent pas le 5 V. C'est le seul montage qui abîme quelque chose.

## Câblage nominal (5 V + pont diviseur)

| HC-SR04 | Pi Zero WH | Broche |
|---|---|---|
| VCC  | 5 V     | pin 2 |
| TRIG | GPIO 23 | pin 16 |
| ECHO | GPIO 24 | pin 18, **via le pont diviseur** |
| GND  | GND     | pin 6 (ou pin 20, plus proche) |

```
        3,3 V [ 1] [ 2] 5 V      ← VCC (ou pin 1 en mode 3,3 V)
       GPIO 2 [ 3] [ 4] 5 V
       GPIO 3 [ 5] [ 6] GND      ← GND
                 ...
        3,3 V [17] [18] GPIO 24  ← ECHO (pont diviseur)
      GPIO 10 [19] [20] GND
      GPIO 22 [15] [16] GPIO 23  ← TRIG
```

Broches par défaut modifiables dans `config.json` ou depuis l'interface. Éviter
GPIO 2/3 (I²C), 14/15 (UART) et 7 à 11 (SPI) si ces bus sont activés —
`preflight.py` vérifie les conflits.

## Placement du capteur

Le HC-SR04 a un cône d'émission d'environ 15°. À 30 cm il « voit » un disque de
8 cm de diamètre.

- Le fixer à plat au sommet de la trémie, faisceau vertical, centré.
- Zone morte de 2 cm : le capteur ne voit rien de plus près. Il faut donc au moins
  2 cm entre la membrane et le niveau haut des croquettes.
- Les parois inclinées renvoient des échos parasites. Si `preflight.py` signale des
  mesures dispersées avec un capteur pourtant bien alimenté, c'est souvent ça :
  décaler le capteur, ou augmenter `samples` dans la config.
- Poussière de croquettes sur les membranes : un coup de soufflette de temps en temps.
