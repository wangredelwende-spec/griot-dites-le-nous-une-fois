# Griot Secure : « Dites-le-nous une fois »

Passerelle d'interopérabilité libre (AGPL-3.0) : les pièces circulent entre administrations, pas les usagers.
Équipe Griot Secure (BIT), finale du Hackathon 226, sujet 02.

<!-- Présentation complète (concept, scénario d'Awa, installation, banc de pannes) : à rédiger par Enock. -->

## Nos registres et leur contrat

Il n'y a pas de contrat commun imposé : chaque équipe définit ses registres. Les nôtres (état civil, nationalité,
casier judiciaire) sont **simulés, avec des données fictives** :

- contrat OpenAPI : `registres/contrat/contrat-registres.yaml` (une route par registre, 404 si le citoyen est inconnu) ;
- citoyens fictifs : `registres/donnees/citoyens-fictifs.yaml` (10 citoyens : majeure, mineure, casier non vierge,
  homonymes, non burkinabè, décédée, « né vers 1990 »…).

Les réponses des registres sont **validées contre le contrat** : une réponse non conforme est rejetée et écrite au
journal. Les noms de champs ne sont écrits qu'une fois, dans `consentement-minimisation/catalogue/correspondance.yaml`.

Les trois démarches du catalogue actif (concours direct de la fonction publique, entreprise individuelle au CEFORE,
certificat de nationalité) sont choisies selon ce que ces registres savent répondre. Changer de démarche ne touche
pas au code : `consentement-minimisation/catalogue/demarches.yaml` (et `attributs.yaml` pour un nouvel attribut).
Le catalogue est relu à chaud et **validé** : une version invalide est refusée, l'ancienne reste en vigueur.
Démarches retirées : `demarches-inactives.yaml`. Limites et fonctions désactivées : `LIMITES.md`.

## Brancher le registre d'une autre équipe

Autre adresse, autres routes, autres noms de champs : **`annuaire.yaml` + `correspondance.yaml`** seulement (plus le
contrat publié par cette équipe, copié tel quel), relus à chaud. Procédure et essai à blanc chronométré :
`docs/brancher-un-registre.md` (`.venv\Scripts\python scripts\essai_a_blanc_autre_equipe.py`).

Tests : `.venv\Scripts\python -m pytest` (un nom de champ oublié dans `correspondance.yaml` fait échouer
`test_correspondance_du_depot_couvre_le_contrat_et_les_attributs`). Avec un autre contrat ou une autre liste de
citoyens : `$env:GRIOT_CONTRAT="…"; $env:GRIOT_CITOYENS="…"; .venv\Scripts\python -m pytest`.

## Voir le portail sans Docker

`.venv\Scripts\python scripts\demo_locale.py` puis http://127.0.0.1:8081/portail (numéro `70000001`, PIN `1234`) et
http://127.0.0.1:8082/ (simulateur `*226#`). Registres simulés, données fictives.
