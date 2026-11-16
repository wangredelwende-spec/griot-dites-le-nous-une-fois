# Fiche oral : Griot Secure, « Dites-le-nous une fois »

Pour l'équipe (Esther, Malkiram, Enock) : de quoi expliquer le système simplement et répondre au jury.
Démonstration pas à pas : `docs/test-manuel.md`.

## Le parcours en une minute (passeport)

1. **Aujourd'hui**, pour un passeport ordinaire, l'usager apporte au service des passeports
   (passeport AES produit par l'ONI) acte de naissance, certificat de nationalité, CNIB et extrait de casier, en copies légalisées.
2. **Avec Griot Secure**, l'agent des passeports (`moussa.kone`) choisit « Passeport ordinaire » et tape
   l'identifiant de l'usager. C'est tout : il ne peut rien demander d'autre que ce que prévoit le catalogue.
3. Le **médiateur** interroge les trois registres **en parallèle** : état civil (« majeur ? »), nationalité
   (« burkinabè ? »), casier (« interdiction de sortie du territoire ? »).
4. Chaque registre calcule la réponse **chez lui** et la **signe** avec sa clé. Il ne renvoie jamais la fiche.
5. **Vous voyez avant** : sur son téléphone (`*226#`), l'usager lit « L'ONI (passeports) recevra : majeur = oui ;
   burkinabè = oui ; interdiction de sortie du territoire = non. Rien d'autre. » et choisit Confirmer ou Refuser.
6. L'agent reçoit les trois réponses signées et le guichet **revérifie lui-même** chaque signature.
7. **Vous vérifiez après** : « Qui a consulté mes données » montre chaque consultation (qui, quand, pourquoi, sur
   quelle base), avec un **reçu** de 16 caractères vérifiable dans le journal.

## Les mécanismes, simplement

- **Signature (Ed25519, bibliothèque PyJWT)** : le registre signe avec sa clé privée, que lui seul possède. Tout le
  monde peut vérifier avec sa clé publique. Si le médiateur changeait « non » en « oui », la signature ne
  correspondrait plus. Le médiateur ne peut donc **ni lire la fiche, ni fabriquer une réponse**.
- **Journal chaîné (SHA-256)** : chaque ligne contient l'empreinte de la précédente. Modifier une ligne casse la
  chaîne à cet endroit, et `verifier.py` dit « Ligne N modifiée ». Le journal note le **fait** (« l'ONI a
  consulté majeur pour un passeport »), jamais la **valeur** (« oui »). Le citoyen y est pseudonymisé (HMAC).
- **Reçu** : les 16 premiers caractères de l'empreinte de la ligne. Si un administrateur réécrivait tout le journal
  en recalculant la chaîne, les reçus déjà donnés aux usagers ne se retrouveraient plus.
- **Double trace** : chaque registre garde, chez lui, la liste des réponses qu'il a signées (sans valeur ni
  citoyen). `verifier.py --registres` la compare au journal : une consultation effacée du journal reste visible
  côté registre.
- **Double clé** : le catalogue dit qui peut demander quoi, et **chaque registre le revérifie lui-même** (service,
  seuils d'âge autorisés). Le registre vérifie aussi le jeton Keycloak de l'agent : le médiateur ne peut pas
  inventer le demandeur.
- **Règle d'or** : en cas de doute, on refuse. Date « vers 1990 », doublon, décès, case vide, valeur inconnue,
  signature fausse, registre trop lent (3 s) ou coupé : refus clair, « rien n'a été deviné ».

## Questions de jury et réponses

**Minimisation (« ne transmettre que l'utile »)**

- *Que reçoit vraiment l'ONI ?* Trois réponses signées : `{"age_equal_or_over": {"18": true}}`,
  `{"nationalite_burkinabe": true}`, `{"interdiction_sortie_territoire": false}`. Ni date de naissance, ni
  filiation, ni casier. Preuve en direct : `scripts/preuve_minimisation.py`, qui cherche les données témoins partout
  hors des registres et ne les trouve pas.
- *Pourquoi « interdiction de sortie » plutôt que « casier vierge » ?* C'est plus minimal. Une condamnation pour vol
  sans interdiction (BF-0005) ne regarde pas le service des passeports : il reçoit seulement « interdiction : non ».
- *Un service peut-il retrouver la date de naissance en posant beaucoup de questions d'âge ?* Non. Chaque registre
  n'accepte que les seuils et dates déclarés pour ce service (double clé sur les paramètres), et un même service ne
  peut pas faire plus de 5 demandes sur la même personne en 24 h.
- *Et le médiateur, que voit-il ?* La réponse minimale signée, gardée seulement jusqu'à la remise ou à
  l'expiration (10 min), puis effacée. Jamais la fiche.

**Consentement et droits de l'usager**

- *Que se passe-t-il si l'usager refuse, ne répond pas, ou change d'avis ?* Refus : rien n'est transmis. Sans réponse
  pendant 10 minutes : expiration, rien n'est remis. Retrait (menu 3) : avant la remise, rien ne part ; après,
  le retrait est écrit au journal et le service ne doit plus utiliser la réponse (on ne peut pas rappeler une
  réponse déjà remise : c'est dit honnêtement à l'usager).
- *Et le concours, sans consentement ?* Base légale (communiqué du concours) : pas d'accord à demander, mais la
  consultation apparaît dans l'historique du candidat avec le texte cité.
- *Un mineur qui demande un passeport ?* « majeur = non » n'est pas un refus : c'est une réponse signée, et le
  guichet affiche « mineur : autorisation parentale requise ». Le consentement par le représentant légal est dans
  la feuille de route.
- *Et un usager sans smartphone ?* Le consentement se fait par USSD (`*226#`), écrans de 160 caractères, sur
  n'importe quel téléphone. Le mooré est prévu ; une langue incomplète n'est pas proposée (jamais de mooré inventé).

**Traçabilité et confiance**

- *Un administrateur peut-il effacer une consultation gênante ?* Modifier une ligne : `verifier.py` la désigne.
  Supprimer une ligne et recalculer toute la chaîne : les reçus des usagers ne se retrouvent plus, et la double
  trace des registres montre la réponse « absente du journal ».
- *Votre remise à zéro ne permet-elle pas de faire disparaître un journal ?* Non : on archive (renommé avec la
  date), on n'efface jamais. L'archive reste vérifiable, avec la trace signée de chaque registre archivée en même
  temps.
- *Qui contrôle les agents ?* Un agent qui consulte plus de 5 citoyens différents en une heure est bloqué, et
  chaque citoyen concerné voit une ALERTE dans son historique. Le contrôleur (`controle.cil`, lecture seule, comme
  un délégué à la protection des données) voit les alertes, l'état des registres, le catalogue et vérifie le
  journal.
- *Le contrôleur peut-il savoir quels citoyens ont été consultés ?* Non : il voit l'agent, le service et le motif,
  jamais d'identifiant, de pseudonyme ni de valeur (un test le vérifie).
- *Comment savoir quelles règles étaient en vigueur lors d'une consultation ?* L'empreinte SHA-256 du catalogue
  est écrite au journal à chaque chargement.

**Pannes (« tenir quand un registre tombe »)**

- *Registre coupé ou lent ?* Après 3 secondes au plus : « Registre … indisponible, rien n'a été deviné », ligne au
  journal. Les deux autres registres répondent quand même, et la conclusion dit « résultat incomplet » : jamais
  de « oui » global sur un résultat partiel.
- *Réponse falsifiée en chemin ?* Signature invalide : refus et ligne d'alerte.
- *Demande envoyée deux fois ?* Même identifiant de demande : une seule exécution, même résultat.
- *Wifi coupé ?* Tout tourne en local, réseaux Docker sans Internet, aucune ressource externe. Images
  sauvegardables hors ligne (`scripts/sauvegarder_hors_ligne.py`).
- *« Casier vierge » et « registre injoignable », c'est pareil ?* Non. Vierge = réponse signée « oui » ;
  injoignable = « indisponible », non signé, rien n'est deviné.

**Données du jury**

- *Vous ne connaissez pas notre format : combien de code faut-il changer ?* Aucun. CSV, Excel, JSON imbriqué,
  SQLite, dump SQL, PDF texte, API HTTP : tout se règle dans le fichier YAML du registre (colonnes, format des
  dates, valeurs « Burkinabè / BF »). Prouvé par des tests sur 3 jeux fictifs de formats différents.
- *Et un PDF scanné ?* Converti une seule fois par OCR (Tesseract, conteneur sans réseau). Toute case douteuse
  reste vide, donc refusée. Les empreintes du PDF et du CSV produit sont notées.
- *Pas d'identifiant commun entre les registres ?* `inspecter_donnees.py` le détecte, et on ne rapproche rien
  sans décision explicite : « en cas de doute, refuser ». Un homonyme sans identifiant sûr donne un refus.

**Réutilisation (« bien commun »)**

- *Un autre ministère peut-il s'en servir ?* Ajouter une démarche = un bloc YAML (`docs/AJOUTER_UNE_DEMARCHE.md`).
  Brancher un registre = un fichier YAML. Exemple d'intégration : e-concours (`docs/API.md`). Tout est libre
  (AGPL-3.0 pour notre code).
- *En production ?* Le médiateur serait ouvert aux seuls systèmes autorisés, avec TLS mutuel, plus le jeton de
  l'agent. Feuille de route : SD-JWT, X-Road, vrai USSD, identifiant unique électronique, consentement du
  représentant légal.
- *Qu'est-ce qui est simulé ?* Les registres (données fictives), la connexion des usagers (numéro + PIN de démo),
  l'USSD (page web qui imite un téléphone). Voir `LIMITES.md`.
