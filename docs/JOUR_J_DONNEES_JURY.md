# Jour J : brancher les données du jury (configuration seulement, aucun code)

Toutes les commandes : PowerShell, dans le dossier du dépôt. Les données du jury restent dans `donnees_jury/`
(ignoré par git : **jamais commitées**).

## Formats acceptés (réglés dans `adaptateurs/<registre>.yaml`)

| Format | `source:` | Réglages |
|---|---|---|
| CSV | `type: csv` | `separateur: auto` (; ou ,), `encodage: auto` (UTF-8, sinon Windows-1252) |
| Excel .xlsx | `type: xlsx` | `feuille:` (sinon la première) ; 1re ligne = noms des colonnes ; dates Excel lues |
| JSON | `type: json` | `liste: registre.personnes` (où est la liste) ; champs imbriqués : `naissance.date` |
| SQLite | `type: sqlite` | `table:` ou `requete: SELECT …` (lecture seule) |
| Dump SQL | `type: sql` | rejoué dans une base SQLite en mémoire ; `table:` ou `requete:` |
| PDF texte | `type: pdf` | tableaux lus avec pdfplumber ; 1re ligne = noms des colonnes |
| PDF scanné | (aucun) | converti **une fois** en CSV par le conteneur OCR (étape 3 bis), puis `type: csv` |
| API HTTP | `type: api` | `url: "http://…?nip={sujet_ref}"`, `liste:`, `delai: 2`, `entetes: {Authorization: "Bearer {secret:api_jury}"}` |

Et aussi, pour tous les formats : `identite:` (colonne qui identifie la personne), `champs:` (noms des colonnes),
`format_date: "%d/%m/%Y"` (ou une liste de formats), `correspondances:` (« Burkinabè », « BF », « burkinabe »…
→ oui ; valeur inconnue → refus). « vers 1990 », case vide, valeur non reconnue : **refus « donnée insuffisante »**.

## Procédure (environ 30 minutes)

**1. Copier** les fichiers du jury dans `donnees_jury\` (ne rien renommer : garder les originaux intacts).

**2. Inspecter** (rien n'est modifié) :
```powershell
.venv\Scripts\python scripts\inspecter_donnees.py donnees_jury\<fichier1> donnees_jury\<fichier2> donnees_jury\<fichier3>
```
Lire : colonnes, formats de date, cases vides, valeurs distinctes (nationalité), identifiant probable, doublons,
homonymes, **identifiant commun entre les fichiers**, et la **clé d'identité proposée** (voir « Identité » plus bas).
S'il n'y a pas d'identifiant commun : la clé composée est proposée ; **en parler à Esther avant de la mettre en
service** (voir `A_TRANCHER_DONNEES_JURY.md`).

**3. Générer les brouillons d'adaptateur** :
```powershell
.venv\Scripts\python scripts\inspecter_donnees.py donnees_jury\<fichier1> donnees_jury\<fichier2> donnees_jury\<fichier3> --proposer-yaml
```
→ `donnees_jury\brouillons\<registre>-<fichier>.yaml`. Les relire : chercher « À VÉRIFIER », vérifier
`identite`, `champs`, `format_date` et **chaque valeur** de `correspondances` (oui / non). Les groupes, attributs
et la double clé sont repris de l'adaptateur actuel : ne pas y toucher. Aussi produits :
`identifiant_usager.yaml` (format de l'identifiant, à recopier dans `catalogue\annuaire.yaml`) et `abonnes.yaml`
(annuaire USSD de démo : numéros et PIN **inventés**, liés à quelques personnes du jury).

**3 bis. PDF scanné seulement** (le conteneur OCR n'a aucun réseau) :
```powershell
docker compose --profile ocr run --rm ocr /donnees/<fichier>.pdf
```
→ `<fichier>.csv` + `<fichier>.provenance.json` (empreintes SHA-256 de l'original et du CSV). Toute case douteuse
reste VIDE (donc refus). Relire le CSV, puis reprendre l'étape 2 sur ce CSV. Option `--seuil 80` (confiance
minimale d'un mot, 0-100).

**4. Tester chaque brouillon** sur des personnes du jury, sans rien signer ni journaliser :
```powershell
.venv\Scripts\python scripts\tester_adaptateur.py etat-civil <identifiant> --yaml donnees_jury\brouillons\<brouillon>.yaml --donnees donnees_jury
```
Essayer au moins : une personne ordinaire, un mineur, une date incomplète, un homonyme, un décès, un casier non
vierge. Chaque refus affiche son motif précis (qui, en vrai, ne sort jamais du registre).

**5. Mettre en service** :
- copier chaque brouillon validé dans `adaptateurs\<registre>.yaml` ;
- si l'identifiant du jury n'est pas de la forme `BF-0001` : recopier `identifiant_usager.yaml` dans
  `catalogue\annuaire.yaml` (bloc `identifiant_usager`) ;
- **annuaire USSD de TOUS les citoyens** (le jury peut désigner n'importe qui) : une fois l'adaptateur d'état civil
  en place, lancer
  ```powershell
  .venv\Scripts\python scripts\annuaire_ussd.py
  ```
  Il lit l'état civil avec le **même code et le même adaptateur** que le registre, donne à chaque citoyen un numéro
  fictif (71000001, 71000002…) et le PIN de démo `1234` (`--pin 4321` pour un autre), puis imprime le tableau
  **identifiant ; nom ; numéro**. Écrit `donnees_jury\abonnes.yaml` (lu par l'USSD) et `donnees_jury\annuaire_ussd.csv`
  (à imprimer pour le jury). L'identifiant imprimé est **exactement** celui à taper au guichet (sinon le téléphone ne
  retrouve pas les demandes de l'usager). Homonymes ou doublon : un seul numéro, marqué « le registre refusera ».
  `--essai` : imprime sans rien écrire. (Remplace `donnees_jury\brouillons\abonnes.yaml`, qui ne couvrait que
  quelques personnes.)
  **Où sont les numéros et les PIN ?** Uniquement dans `donnees_jury\abonnes.yaml` (hors dépôt git), monté en lecture
  seule dans le seul conteneur `ussd_sim`. Les PIN y sont **en clair, non hachés** : ce sont des PIN de démo,
  identiques pour tous et imprimés sur le tableau. Le simulateur bloque 5 minutes après 3 PIN faux. En production,
  ni numéro ni PIN dans un fichier : le numéro vient de l'opérateur, le PIN du fournisseur d'identité (`LIMITES.md`).
- dans `.env` : `DONNEES_REGISTRES=./donnees_jury`, `ABONNES_USSD=./donnees_jury/abonnes.yaml`
  (et `API_JURY_SECRET=…` si le jury donne une API) ;
- redémarrer **seulement les registres, le médiateur, le guichet et l'USSD** (jamais Keycloak ni PostgreSQL ;
  prévenir l'équipe) :
```powershell
docker compose up -d --force-recreate --no-deps --wait registre-etat-civil registre-nationalite registre-casier mediateur guichet ussd_sim
docker compose logs registre-etat-civil registre-nationalite registre-casier | Select-String "source"
```
Chaque registre écrit : format, nombre de lignes et **empreinte SHA-256** du fichier lu. Un YAML ou un fichier
illisible : le registre refuse de démarrer, avec le motif (`docker compose logs registre-…`).

**6. Vérifier** : `python scripts\remise_a_zero.py --oui` (journal neuf), puis le banc de pannes en mode test
(`docs/test-manuel.md`, « Banc de pannes automatique ») → 21/21 attendu, puis une démarche Passeport au guichet
sur une personne du jury.

**Revenir aux données fictives** : `DONNEES_REGISTRES=./registres_sim/donnees_fictives` et
`ABONNES_USSD=./ussd_sim/abonnes.yaml` dans `.env`, `git checkout adaptateurs\ catalogue\annuaire.yaml`, puis la
commande de l'étape 5.

## Identité : retrouver la bonne personne dans chaque registre

Trois réglages, tous en configuration :

1. **Clé d'identité du registre** (`identite:` dans `adaptateurs\<registre>.yaml`) :
   - identifiant commun aux registres s'il existe : `identite: nip` (comparé tel quel) ;
   - sinon **clé composée** : `identite: {colonnes: [Nom, Prénoms, Date de naissance], separateur: "|"}`
     (ajouter `Lieu de naissance` si l'inspection montre qu'il départage des homonymes). L'identifiant de l'usager
     devient `KABORE|Aminata|2001-03-14`. Chaque morceau est comparé sans accents, majuscules ni espaces en trop, et
     les dates sont ramenées à `2001-03-14` (jj/mm/aaaa accepté). **Comparaison exacte** : une lettre ou un jour de
     différence = « introuvable » ; plusieurs fiches pour la même clé = refus « identité ambiguë : homonymes ».
     Une date incomplète (« vers 1990 ») ne correspond jamais.
   - Les **trois** registres doivent utiliser la **même** clé (mêmes morceaux, même ordre).
2. **Format de l'identifiant** (`identifiant_usager:` dans `catalogue\annuaire.yaml`) : expression régulière +
   exemple. Le guichet l'affiche en exemple grisé et refuse un identifiant mal formé ; le médiateur le revérifie.
   Pas de « / » (il passe dans les adresses de l'API).
3. **Annuaire USSD** (`ABONNES_USSD` dans `.env`) : numéro de téléphone → identifiant + PIN, dans un fichier séparé
   des registres (les données du jury n'ont ni téléphone ni PIN). Numéros et PIN **fictifs** ; en production, le
   numéro vient de l'opérateur et le PIN du fournisseur d'identité.

## Repli : le casier du jury n'a pas de colonne « peines complémentaires »

La démarche Passeport demande normalement l'attribut `interdiction_sortie_territoire` (le plus minimal : le
service des passeports n'a pas à savoir si le casier est vierge). Si le casier du jury n'a **pas** de colonne
« peines complémentaires », cet attribut ne peut plus être calculé : on bascule la démarche sur
« casier judiciaire vierge » en changeant **UNE SEULE LIGNE** du catalogue, sans toucher au code.

Dans `catalogue\demarches.yaml`, démarche `passeport-ordinaire`, remplacer la ligne :

```yaml
      - {attribut: interdiction_sortie_territoire, libelle: interdiction de sortie du territoire, attendu: false}
```

par la ligne « repli » donnée en commentaire juste en dessous :

```yaml
      - {attribut: casier_judiciaire_vierge, libelle: casier judiciaire vierge, si_non: "casier non vierge : dossier à instruire"}
```

Puis `docker compose restart mediateur guichet`. Rien d'autre :

- le registre casier **autorise déjà** le service passeport sur « casier vierge » (double clé déclarée dans
  `adaptateurs\casier.yaml` — c'est le seul autre service autorisé avec la Direction des concours) ;
- l'aperçu USSD suit tout seul : il est fabriqué depuis le catalogue (« … recevra : casier judiciaire
  vierge = oui/non. Rien d'autre. », moins de 160 caractères), jamais en dur ;
- si l'adaptateur casier du jury ne déclare plus `interdiction_sortie_territoire` (colonne absente), la ligne
  d'origine ferait refuser le démarrage du médiateur (« attribut inconnu ») : la bascule est obligatoire.

**Plus large, donc à ne faire que si la colonne manque** : avec le repli, le service des passeports apprend
qu'une personne a été condamnée (casier non vierge) même sans interdiction de sortie. Revenir à l'attribut
normal dès que la colonne existe. Testé : les deux réglages passent la suite (`tests\test_catalogue.py`).

## API du jury

**Par défaut : un export unique**, puis un fichier comme les autres (les registres restent sans réseau) :
```powershell
.venv\Scripts\python scripts\exporter_api_jury.py "<adresse de l'API>" etat_civil
```
→ `donnees_jury\etat_civil.json` + `etat_civil.provenance.json` (adresse sans identifiant, date, empreinte
SHA-256). Le jeton éventuel est pris dans `.env` (`API_JURY_SECRET`) et n'est écrit nulle part. Puis étapes 2 à 6
(source `type: json`).

**Seulement si le jury impose l'API en direct** : profil `api-jury`. Un **relais** est le seul conteneur relié au
réseau extérieur ; il ne transmet qu'à l'adresse `API_JURY_URL` de `.env`, en lecture (GET), avec un délai de 2 s
(sous les 3 s du médiateur), et ajoute lui-même le jeton (`API_JURY_SECRET`). Les registres le joignent par un
réseau interne sans sortie : ils ne connaissent ni l'adresse de l'API ni son jeton.
1. `.env` : `API_JURY_URL=http://<adresse>:<port>` (sans chemin) et `API_JURY_SECRET=…`.
2. Adaptateur : `source: {type: api, url: "http://relais-api-jury:8080/<chemin>?<param>={sujet_ref}", liste: …,
   delai: 2}` (pas d'`entetes` : le relais ajoute le jeton).
3. Lancer le relais (prévenir l'équipe ; jamais Keycloak ni PostgreSQL) :
```powershell
docker compose --profile api-jury up -d --build --no-deps --wait relais-api-jury
docker compose up -d --force-recreate --no-deps --wait registre-etat-civil registre-nationalite registre-casier
```
API coupée ou trop lente : le relais répond 504, le registre « indisponible », le guichet « rien n'a été deviné ».
