# Couche « journal de traçabilité »

**Rôle** : « vous vérifiez après ». Prouver qui a consulté quoi, quand et pourquoi, et qu'aucune ligne n'a été
modifiée.

## Ce que contient la couche

| Fichier | Rôle |
|---|---|
| `tracabilite/journal.py` | journal SQLite en **ajout seul** (déclencheurs qui refusent UPDATE et DELETE), chaîné par SHA-256 |
| `verifier.py` | recalcule toute la chaîne : « Journal intègre : N lignes » ou « Ligne N modifiée » ; vérifie un reçu ; compare avec la double trace des registres |

`tracabilite/` tourne dans le processus de la passerelle d'échange (copié dans son image).

## Une ligne

`hash = SHA-256(prev_hash + JSON canonique de la ligne sans hash)` ; première ligne : 64 zéros.
Le journal consigne **le fait, jamais le contenu** : « le service des bourses a consulté l'attribut majeur de X
pour une bourse », jamais « majeur = oui ». Le citoyen y est pseudonymisé (HMAC-SHA256 avec un secret de la
passerelle).

**Reçu** : les 16 premiers caractères de l'empreinte de la ligne, donnés à l'usager. Si quelqu'un recalculait toute
la chaîne, les reçus déjà remis ne correspondraient plus.

**Double trace** : chaque registre garde sa propre liste des réponses qu'il a signées (sans la valeur) ;
`verifier.py --registres` la compare au journal. Une consultation cachée se voit.

## Contrat

`openapi.yaml` (généré, vérifié par `tests/test_openapi.py`) :

| Route | Qui l'appelle |
|---|---|
| `GET /usagers/{sujet_ref}/historique` | espace usager (secret du canal) : « Qui a consulté mes données », jamais la valeur |
| `GET /controle/verification` | contrôleur (lecture seule) : même vérification que `verifier.py --registres` |

En ligne de commande : `docker compose exec mediateur python /journal/verifier.py [--recu "9035 47b3 1c2e 9f04"] [--registres]`.

## Tests

`journal/tests/` : canal de l'usager écrit au journal, ajout de colonne sans changer les anciennes empreintes.
La chaîne, les reçus et la falsification sont aussi testés dans `passerelle/tests/test_mediateur.py`.
