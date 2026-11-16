# API usager du médiateur (figée le 16/11/2026, catalogue multi-attributs le 16/11 après-midi)

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
[{"id_demande": "8c1f…", "service": "Le service des bourses", "code_service": "service-bourses",
  "demarche": "Bourse nationale", "finalite": "attribution de la bourse nationale",
  "attributs": [{"code": "nationalite_burkinabe", "libelle": "nationalité burkinabè", "parametres": {},
                 "valeur": "oui"}],
  "expire_le": 1794838200,
  "apercu": "Le service des bourses recevra : nationalité burkinabè = oui. Rien d'autre."}]
```

- **Une demande peut porter plusieurs attributs** (démarche du catalogue) : UN aperçu les liste tous,
  UNE confirmation vaut pour tous.
- `code_service`, `attributs[].code` : codes stables pour composer l'écran dans une autre langue ;
  les textes `service`, `libelle`, `apercu` restent en français.
- `valeur` : `"oui"` ou `"non"`, exactement ce qui partira si l'usager confirme.
- `expire_le` : horodatage Unix (UTC) ; après, la demande disparaît (expirée, rien n'est remis).

## 2. Confirmer ou refuser

`POST /demandes/{id_demande}/confirmer` et `POST /demandes/{id_demande}/refuser`, corps JSON :

```json
{"sujet_ref": "BF-0012"}
```

| Réponse | Sens |
|---|---|
| `200 {"id_demande": "…", "statut": "confirmee", "empreinte": "<64 hex>"}` | confirmé ; `empreinte` = reçu de la confirmation (USSD : 16 premiers caractères, en 4 groupes de 4) |
| `200 {"id_demande": "…", "statut": "refuse"}` | refusé : rien ne sera transmis |
| `404` | demande inconnue **ou** appartenant à un autre usager (on ne distingue pas) |
| `409 {"detail": "demande déjà traitée (statut : …)"}` | déjà confirmée, refusée ou expirée |

## 2 bis. Retirer un accord

`GET /usagers/{sujet_ref}/accords` → accords donnés (base consentement), du plus récent au plus ancien (9 au plus) :

```json
[{"id_demande": "8c1f…", "code_service": "service-bourses", "service": "Le service des bourses",
  "demarche": "Bourse nationale", "attributs": [{"code": "nationalite_burkinabe", "libelle": "nationalité burkinabè"}],
  "transmis": false}]
```

`POST /demandes/{id_demande}/retirer`, corps `{"sujet_ref": "BF-0012"}` :

| Réponse | Sens |
|---|---|
| `200 {"statut": "retiree", "transmis": false, "empreinte": "…"}` | pas encore remis : plus rien ne partira |
| `200 {"statut": "retiree_apres_remise", "transmis": true, "empreinte": "…"}` | déjà remis : retrait écrit au journal, le service ne doit plus utiliser la réponse |
| `404` / `409` | demande inconnue ou d'un autre usager / base légale ou déjà retirée |

## 3. Historique : qui a consulté mes données

`GET /usagers/{sujet_ref}/historique` → `200`, du plus récent au plus ancien (100 lignes au plus) :

```json
[{"n": 36, "ts": "2026-11-16T11:54:30Z", "agent": "issa.sawadogo",
  "service": "La Direction des concours – ministère des Serviteurs du peuple", "code_service": "direction-concours",
  "demarche": "Concours direct adjoints administratifs",
  "finalite": "vérification des conditions d'inscription au concours direct des adjoints administratifs",
  "base": "base_legale", "texte_base": "Loi n°081-2015/CNT …",
  "attributs": [{"code": "age_entre", "libelle": "âge de 18 à 37 ans au 31/12/2026"},
                {"code": "nationalite_burkinabe", "libelle": "nationalité burkinabè"},
                {"code": "casier_judiciaire_vierge", "libelle": "casier judiciaire vierge"}],
  "evenement": "remise", "resultat": "ok", "motif": "",
  "empreinte": "038672c337eaa71a…"}]
```

- **Jamais la valeur** de l'attribut : le journal ne la contient pas.
- `base` : `consentement` ou `base_legale` (alors `texte_base` donne le texte qui l'autorise).
- `attributs` : ce que concerne la ligne (une ligne `reponse-registre` ne concerne qu'un attribut).
- `evenement` : `demande` | `reponse-registre` | `confirmation` | `refus-usager` | `remise` | `expiration` | `alerte` | `retrait`.
- `resultat` : `ok` | `refuse` | `indisponible`. `motif` explique un refus.
- **Reçu** = 16 premiers caractères de `empreinte` (64 bits), affichés « 9035 47b3 1c2e 9f04 ». Il se vérifie avec
  `docker compose exec mediateur python /journal/verifier.py --recu "9035 47b3 1c2e 9f04"`.
- Pour un écran court, ne garder que les lignes `remise`, `refus-usager`, `expiration` et `alerte`.

## Essayer à la main

```sh
docker compose exec mediateur python -c "import httpx,pathlib; c=pathlib.Path('/run/secrets/canal_usager').read_text().strip(); print(httpx.get('http://127.0.0.1:8000/usagers/BF-0001/historique', headers={'X-Cle-Canal': c}).json()[:2])"
```
