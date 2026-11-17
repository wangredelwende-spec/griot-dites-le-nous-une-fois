# Couche « espace usager » (USSD simulé et portail web)

**Rôle** : donner au citoyen la main sur ses données, même sans smartphone. Deux écrans, deux conteneurs, aucun
JavaScript, aucune ressource externe.

| Écran | Adresse | Ce qu'il permet |
|---|---|---|
| `ussd/` (service `ussd_sim`) | `https://usager.griot.test/` | téléphone simple, menu `*226#`, écrans de 160 caractères au plus |
| `portail/` (service `portail`) | `https://usager.griot.test/portail` | les mêmes actions dans un navigateur |

Les deux : connexion par numéro de téléphone + PIN fictifs (`ussd/abonnes.yaml`, ou l'annuaire du jury),
blocage après 3 PIN faux ; demandes en attente avec l'aperçu exact, confirmer ou refuser ; « Qui a consulté mes
données » (paginé, sans jamais la valeur) avec le **reçu** (empreinte en 4 groupes) ; retrait d'un accord.
Langue : français, mooré seulement quand toutes ses phrases sont traduites par l'équipe (jamais de mooré inventé).

## Ce que la couche appelle

Uniquement l'API de la couche **consentement et minimisation** (`consentement-minimisation/openapi.yaml`) et
l'historique du **journal de traçabilité** (`journal/openapi.yaml`), avec **son** secret de canal
(`X-Cle-Canal`) : la passerelle écrit donc « canal = ussd » ou « canal = web » au journal sans croire l'écran sur
parole. Un citoyen ne voit et n'agit que sur ses propres demandes.

## Contrat

`openapi.yaml` (généré, vérifié par `tests/test_openapi.py`) : les formulaires HTML des deux écrans (`/…` pour
l'USSD, `/portail/…` pour le portail). Textes : `traduction-moore/phrases-ussd.csv` et `phrases-portail.csv`.

## Tests

`espace-usager/tests/` : USSD (160 caractères, pagination, PIN), portail, isolement entre citoyens, annuaire USSD
des données du jury. `.venv\Scripts\python -m pytest espace-usager\tests`.
