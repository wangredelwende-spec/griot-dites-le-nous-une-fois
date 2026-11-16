# API usager du médiateur (figée le 16/11/2026)

Utilisée par les écrans usager : **USSD simulé** (`ussd_sim/`, d'abord) puis portail web.
Elle est indépendante de l'écran : le texte d'aperçu est fourni, mais aussi ses morceaux, pour
composer l'écran dans une autre langue (mooré).

## Accès

- Adresse : `http://mediateur:8000`, **réseau Docker `interne` seulement** (jamais publiée par Caddy).
- Chaque appel porte l'en-tête `X-Cle-Canal: <secret>` ; le secret est le fichier `/run/secrets/canal_usager`
  (variable `CANAL_USAGER_SECRET` du `.env`). Sans lui : `401`.
- **L'écran authentifie l'usager** (USSD : numéro + PIN ; portail : Keycloak) et ne transmet que SON `sujet_ref`.
- `sujet_ref` : lettres, chiffres et tirets, 1 à 64 caractères (ex. `BF-0012`).

## 1. Demandes en attente

`GET /usagers/{sujet_ref}/en-attente` → `200`, liste (vide si rien en attente) :

```json
[{"id_demande": "8c1f…", "service": "Le service des bourses", "demarche": "Demande de bourse",
  "finalite": "attribution de bourse", "attribut": "majeur", "valeur": "oui", "expire_le": 1794838200,
  "apercu": "Le service des bourses recevra : majeur = oui. Rien d'autre."}]
```

- `valeur` : `"oui"` ou `"non"`, exactement ce qui partira si l'usager confirme.
- `expire_le` : horodatage Unix (UTC) ; après, la demande disparaît (expirée, rien n'est remis).

## 2. Confirmer ou refuser

`POST /demandes/{id_demande}/confirmer` et `POST /demandes/{id_demande}/refuser`, corps JSON :

```json
{"sujet_ref": "BF-0012"}
```

| Réponse | Sens |
|---|---|
| `200 {"id_demande": "…", "statut": "confirmee", "empreinte": "<64 hex>"}` | confirmé ; `empreinte` = reçu de la confirmation (USSD : afficher les 8 premiers caractères) |
| `200 {"id_demande": "…", "statut": "refuse"}` | refusé : rien ne sera transmis |
| `404` | demande inconnue **ou** appartenant à un autre usager (on ne distingue pas) |
| `409 {"detail": "demande déjà traitée (statut : …)"}` | déjà confirmée, refusée ou expirée |

## 3. Historique : qui a consulté mes données

`GET /usagers/{sujet_ref}/historique` → `200`, du plus récent au plus ancien (100 lignes au plus) :

```json
[{"n": 36, "ts": "2026-11-16T11:54:30Z", "agent": "issa.sawadogo",
  "service": "La direction des concours de la fonction publique",
  "demarche": "Inscription à un concours de la fonction publique",
  "finalite": "vérification de l'âge minimal pour concourir", "base": "base-legale",
  "texte_base": "Règlement des concours … (texte fictif pour la démonstration)",
  "attribut": "majeur", "evenement": "remise", "resultat": "ok", "motif": "",
  "empreinte": "038672c337eaa71a…"}]
```

- **Jamais la valeur** de l'attribut : le journal ne la contient pas.
- `base` : `consentement` ou `base-legale` (alors `texte_base` donne le texte qui l'autorise).
- `evenement` : `demande` | `reponse-registre` | `confirmation` | `refus-usager` | `remise` | `expiration` | `alerte`.
- `resultat` : `ok` | `refuse` | `indisponible`. `motif` explique un refus.
- **Reçu** = `empreinte` (USSD : 8 premiers caractères). Il se vérifie avec
  `docker compose exec mediateur python /journal/verifier.py --recu <8 caractères ou plus>`.
- Pour un écran court, ne garder que les lignes `remise`, `refus-usager`, `expiration` et `alerte`.

## Essayer à la main

```sh
docker compose exec mediateur python -c "import httpx,pathlib; c=pathlib.Path('/run/secrets/canal_usager').read_text().strip(); print(httpx.get('http://127.0.0.1:8000/usagers/BF-0001/historique', headers={'X-Cle-Canal': c}).json()[:2])"
```
