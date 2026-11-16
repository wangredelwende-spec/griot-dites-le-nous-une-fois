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
`identifiant_usager.yaml` (format de l'identifiant, à recopier dans `cataloguennuaire.yaml`) et `abonnes.yaml`
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
  `cataloguennuaire.yaml` (bloc `identifiant_usager`) ;
- copier `donnees_juryrouillonsbonnes.yaml` dans `donnees_jurybonnes.yaml` ;
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
(`docs/test-manuel.md`, « Banc de pannes automatique ») → 18/18 attendu, puis une démarche Passeport au guichet
sur une personne du jury.

**Revenir aux données fictives** : `DONNEES_REGISTRES=./registres_sim/donnees_fictives` et
`ABONNES_USSD=./ussd_sim/abonnes.yaml` dans `.env`, `git checkout adaptateurs\ cataloguennuaire.yaml`, puis la
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
2. **Format de l'identifiant** (`identifiant_usager:` dans `cataloguennuaire.yaml`) : expression régulière +
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

## API du jury : réseau

Les registres sont sur des réseaux Docker **sans Internet**. Si l'API du jury est sur le réseau local, le registre
ne peut pas la joindre tel quel : voir `A_TRANCHER_DONNEES_JURY.md` (décision d'Esther avant de l'ouvrir).
