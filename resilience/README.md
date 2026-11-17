# Couche « résilience »

**Rôle** : prouver que la pile tient quand un registre tombe, et pouvoir le rejouer devant le jury.

| Fichier | Rôle |
|---|---|
| `panne.py` | interrupteur : `python resilience/panne.py <registre> normal\|lent\|eteint\|non_conforme` (variable `PANNE`, le registre est recréé) |
| `banc_de_pannes.py` | joue les situations de l'épreuve contre la pile qui tourne, ✅ / ❌ ligne par ligne |
| `falsifier_journal.py` | modifie une copie du journal pour montrer que `verifier.py` désigne la ligne |
| `sauvegarder_hors_ligne.py`, `charger_hors_ligne.py` | `docker save` de toutes les images, et rechargement sans réseau |
| `ancien/` | ancien banc (registres signés), conservé, non utilisé |
| `tests/` | tests du banc et de la remise à zéro |

Règle d'or : au moindre doute, refus avec un motif ; « registre indisponible, rien n'a été deviné ».
Pas de contrat OpenAPI : cette couche n'expose aucune API, elle pilote les autres.
