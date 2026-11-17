# Brouillon mooré des écrans USSD : à relire

`phrases-ussd-brouillon.csv` est un **brouillon produit par une IA (Claude)**, pas une traduction.
Il ne s'affiche **jamais** dans la démo : le simulateur USSD ne lit que `phrases-ussd.csv`
(seul fichier monté dans le conteneur `ussd`, voir `docker-compose.yml`). Le brouillon est un fichier à part.

## Structure de `phrases-ussd.csv` (fichier officiel, non modifié)

- Séparateur `;`, UTF-8. Colonnes : `cle ; ecran ; fr ; mos ; dyu ; ff` (`mos` = mooré).
- **67 phrases** (plus l'en-tête). Les colonnes `mos`, `dyu`, `ff` sont vides.
- Repères remplacés par le programme : `{service}`, `{liste}`, `{attributs}`, `{finalite}`, `{recu}`, `{n}`.
- Une langue n'est proposée que si **toutes** ses phrases sont remplies : on peut donc valider ligne par ligne
  sans risque, le mooré n'apparaîtra qu'une fois les 67 lignes remplies.

## Colonnes du brouillon

`cle ; francais ; moore_brouillon_ia ; statut ; doutes ; longueur_max ; hors_gsm`

- `longueur_max` : longueur de la phrase mooré après remplacement des repères par la valeur la plus longue
  (`{service}` = « Concours tʋʋm-zĩigã », `{liste}` = les 3 attributs du concours en version longue,
  `{finalite}` = la finalité du concours (88 caractères), `{recu}` = 19 caractères, `{n}` = 3).
- `hors_gsm` : `oui` si la phrase contient une lettre absente de l'alphabet GSM 03.38 (ɛ, ɩ, ʋ, ã, ẽ, ĩ, õ, ũ, ç…).
  Sur un vrai réseau USSD, ces lettres obligent à passer en UCS-2 : **70 caractères par message au lieu de 160**,
  ou bien elles s'affichent mal. Le simulateur, lui, les affiche correctement.

## Comment corriger

1. Ouvrir `phrases-ussd-brouillon.csv` (LibreOffice ou Excel : CSV UTF-8, séparateur point-virgule).
2. Pour chaque ligne : lire `francais`, le brouillon et les `doutes`, puis écrire la version juste.
3. Copier la version juste dans la colonne **`mos`** de `phrases-ussd.csv`, sur la ligne de même `cle`.
   Ne toucher ni à `cle`, ni à `ecran`, ni à `fr`. Garder les repères `{…}` **exactement** (accolades comprises).
4. Dans le brouillon, passer `statut` de « à relire » à « validé ».
5. Enregistrer `phrases-ussd.csv` en **CSV UTF-8, séparateur point-virgule** (sinon ɛ, ɩ, ʋ sont perdus).
6. Une fois les 67 lignes validées, prévenir Esther : la langue s'active au redémarrage du conteneur `ussd`.

## À vérifier en priorité

### 1. Phrases de la démo et phrases difficiles (sens)

| Clé | Pourquoi |
|---|---|
| `apercu` | Phrase clé de l'épreuve : « {service} recevra : … Rien d'autre. » |
| `confirmer_refuser`, `oui`, `non` | Affichés dans l'aperçu (« = ẽe ») |
| `retrait_apres` | La plus difficile : « déjà transmis, le service ne doit plus l'utiliser » |
| `base_legale`, `base_consentement` | Notions juridiques |
| `menu_historique`, `historique_vide` | « données » rendu par « kibaya » : à confirmer |
| `menu_retrait`, `accords_titre`, `aucun_accord`, `retrait_*` | « accord » rendu par « sakre » : à confirmer |
| `deja_traitee`, `indisponible`, `refuse` | « Rien n'a été transmis » rendu par « Bũmb pa loog ye » |
| `pin_faux`, `bloque`, `au_revoir` | Tournures incertaines |
| `telephone_allumer`, `telephone_envoyer`, `telephone_raccrocher` | Verbes très incertains |

**55 lignes sur 67** ont un doute sur le sens ou l'écriture (colonne `doutes`).
Seules 6 n'en ont pas : `historique_vide`, `etat_expiration`, `etat_retrait`, `retrait_confirmer`, `langue`, `non`.

### 2. Mots gardés en français (choix à confirmer)

PIN, code, menu, reçu, ALERTE, bourse, concours, casier judiciaire vierge, simulation ; écrits comme à l'oral :
meeri (mairie), paspoor (passeport), minit (minute).
**Attention** : `{finalite}` reste toujours en français (elle vient du catalogue), même sur un écran en mooré.
De même, le libellé long de l'âge (« âge de 18 à 37 ans au 31/12/2026 ») n'a pas de clé dans le fichier :
il s'affiche en français.

### 3. Longueur (160 caractères)

- **Aucune phrase seule ne dépasse 160** caractères. Les plus longues : `apercu` 140, `retrait_apres` 100, `pour` 96.
- Écrans assemblés (plusieurs phrases) : l'aperçu du concours avec libellés longs ferait 185 caractères ;
  le programme passe alors tout seul aux libellés courts (136 caractères, « yʋʋmã = ẽe ; Burk. = ẽe ; casier = ẽe »).
  Après correction, garder `attribut_court_*` **très courts**. Menu principal : 70 caractères.
- Sur un vrai réseau, toute ligne `hors_gsm = oui` est limitée à **70 caractères** (voir plus haut) :
  `apercu`, `retrait_apres`, `pour` dépasseraient.

### 4. Lettres hors GSM : 41 lignes

composer, code_inconnu, non_inscrit, pin_faux, bloque, session_expiree, menu_attente, menu_historique,
menu_retrait, choix_invalide, aucune_demande, apercu, confirmer_refuser, suivante, confirme, refuse,
deja_traitee, suite, pour, base_legale, base_consentement, recu, etat_remise, etat_refuse, accords_titre,
accord_en_cours, retrait_question, retrait_fait, retrait_apres, au_revoir, indisponible, oui,
service_long_service-bourses, service_long_direction-concours, service_long_mairie,
attribut_nationalite_burkinabe, attribut_court_age_entre, attribut_interdiction_sortie_territoire,
attribut_court_interdiction_sortie_territoire, telephone_numero, telephone_envoyer.

Question à trancher par l'équipe : garder l'orthographe officielle (ɛ, ɩ, ʋ, tildes) pour la démo, ou prévoir
une version « GSM » sans ces lettres pour un vrai réseau (à noter dans LIMITES.md / FEUILLE_DE_ROUTE.md).
Remarque : le « ç » de « Reçu » existe en GSM seulement en majuscule (Ç) ; certains téléphones l'affichent mal.
Le français a le même souci avec « âge » (â hors GSM).
