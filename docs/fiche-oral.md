# Fiche oral : Griot Secure, « Dites-le-nous une fois »

Pour l'équipe (Esther, Malkiram, Enock) : de quoi répondre au jury et expliquer le système simplement.
Démonstration pas à pas : `docs/test-manuel.md`.

## Les 22 questions du jury

1. **Pourquoi l'accord de l'usager si le service a déjà l'acte ?** → Avec nous il ne l'a plus ; l'accord empêche les consultations en cachette ; en base légale, pas d'accord mais visible dans l'historique.
2. **Mots de passe en clair ?** → Fictifs, TOTP obligatoire, anti-force brute, Keycloak local ; en production realm sans utilisateurs.
3. **Keycloak tombe ?** → Journal indépendant ; jeton valable jusqu'à expiration, puis refus clair.
4. **Le médiateur peut-il lire la date ou répondre « oui » ?** → Non : le registre calcule et signe ; le guichet revérifie ; clé publique non remplaçable.
5. **Ligne du journal supprimée ?** → Reçus des usagers + double trace des registres.
6. **Médiateur piraté ?** → Le registre vérifie lui-même le jeton signé de l'agent ; tout est aussi tracé chez le registre.
7. **Seuils multiples pour retrouver la date ?** → Seuils déclarés par service, refus des autres ; limite 5/24 h par service et par personne + alerte.
8. **Majeur = 18 ou 20 ans ?** → 18 depuis la loi n°012-2025/ALT ; paramètre.
9. **Absent du casier = vierge ?** → Réglable ; vierge seulement si identité confirmée.
10. **Registre en panne pendant une démarche à 3 registres ?** → Résultat partiel signé, jamais de « oui » global, « rien n'a été deviné ».
11. **Pourquoi pas de base centrale ?** → Elle permettrait de tout croiser ; chaque registre garde ses données.
12. **Pourquoi pas X-Road ?** → Trop lourd en 3 jours ; principes repris, migration documentée.
13. **Vrai USSD ?** → Passerelle opérateur (Orange/Moov) ; simulateur sur la même API.
14. **Le e-casier existe déjà ?** → Même en ligne le citoyen transporte le document ; ici le service reçoit seulement « vierge : oui/non ».
15. **Qui administre ?** → Rôles séparés ; contrôleur en lecture seule ; personne n'a tous les pouvoirs.
16. **Un mineur peut-il consentir ?** → Non traité ; loi 001-2021 : représentant légal ; feuille de route.
17. **Données en Excel/PDF ?** → Réglage YAML, conversion à l'import, champ douteux vide = refus.
18. **La remise à zéro efface-t-elle le journal ?** → Non, elle archive ; archive vérifiable ; trace signée de chaque registre archivée aussi.
19. **Le contrôleur voit-il les citoyens consultés ?** → Non : agent, service, motif, nombre ; jamais d'identifiant ni de pseudonyme.
20. **Comptes de test qui contournent ?** → Seulement si OUTILS_TEST=1, désactivés en démo, marqués au journal.
21. **e-concours existe déjà ?** → Il numérise l'inscription, pas la vérification : les dossiers physiques sont encore demandés après ; e-concours deviendrait un service demandeur du médiateur.
22. **Pourquoi l'usager doit confirmer « majeur » ?** → Consentement « exprès, libre, spécifique et éclairé » (loi 001-2021) ; il voit exactement ce qui part ; il ne déclare pas être majeur, c'est le registre qui le prouve.

## Questions en plus

**Minimisation**

23. **Que reçoit vraiment l'ONI ?** → Deux réponses signées : `{"nationalite_bf": true}` et `{"interdiction_sortie_territoire": false}`. Ni date de naissance, ni filiation, ni casier. Preuve en direct : `scripts/preuve_minimisation.py`.
23 bis. **Pourquoi pas « majeur » pour le passeport ?** → L'ONI connaît déjà la date de naissance : c'est lui qui enrôle la carte d'identité (CNIB). La redemander à l'état civil ne servirait à rien, et « ne transmettre que l'utile » vaut aussi pour ce qui est inutile parce que déjà connu. La double clé le garantit : le registre de l'état civil refuse lui-même de donner l'âge à l'ONI. La minimisation de l'âge se montre avec le concours (18–37 ans au 31/12/2026, jamais la date de naissance).
24. **Pourquoi « interdiction de sortie » plutôt que « casier vierge » ?** → C'est plus minimal : une condamnation pour vol sans interdiction (BF-0005) ne regarde pas le service des passeports. Si le casier du jury n'a pas cette colonne, repli en une ligne de catalogue vers « casier vierge ».
25. **Si l'ONI apprend seulement « pas d'interdiction de sortie », comment sait-il qu'un casier mal tenu ne cache pas une interdiction ?** → Une case vide n'est jamais lue comme « aucune » : le registre exige « aucune » écrit en toutes lettres, sinon il répond « donnée insuffisante » (BF-0015).
26. **Et le médiateur, que garde-t-il ?** → La réponse minimale signée, seulement jusqu'à la remise ou l'expiration (10 min), puis effacée. Jamais la fiche.

**Consentement et usager**

26 bis. **Le service pourrait-il passer une démarche en « base légale » pour se passer de l'accord de l'usager ?** → Non : chaque registre déclare, par service, le mode accepté et les textes de loi qu'il reconnaît. Le passeport passé en base légale est refusé au chargement du catalogue et par le registre lui-même (réponse signée).

27. **L'usager refuse, ne répond pas ou change d'avis ?** → Refus : rien n'est transmis. 10 minutes sans réponse : expiration, rien n'est remis. Retrait (menu 3) : avant la remise, rien ne part ; après, le retrait est écrit au journal et le service ne doit plus utiliser la réponse (on le dit honnêtement à l'usager).
27 bis. **Le registre sait-il que l'usager a vraiment dit oui ?** → Non, et on le dit franchement : le registre répond avant l'accord, c'est le médiateur qui retient la réponse jusqu'à la confirmation. Mais une consultation sans accord ne peut pas se cacher : elle apparaît dans l'historique de l'usager (« transmis » sans reçu de confirmation de sa part), et le registre garde sa propre trace signée des réponses qu'il a données, que `verifier.py --registres` compare au journal. Plus tard : accord signé par l'usager lui-même, vérifiable par le registre.
28. **Et un usager sans smartphone ?** → USSD `*226#`, écrans de 160 caractères, sur n'importe quel téléphone. Le mooré est prévu ; une langue incomplète n'est pas proposée (jamais de mooré inventé). Sur le téléphone comme sur le portail web, un citoyen ne voit et n'agit que sur SES demandes : changer l'identifiant dans l'adresse ou le formulaire ne donne rien (prouvé par le test `espace-usager/tests/test_isolement.py`, commit `c793675`, contre le vrai médiateur).

**Traçabilité et pannes**

29. **Un agent peut-il consulter tout le monde ?** → Au-delà de 5 citoyens différents en une heure, il est bloqué et chaque citoyen concerné voit une ALERTE ; le contrôleur la voit aussi.
30. **Quelles règles étaient en vigueur lors d'une consultation ?** → L'empreinte SHA-256 du catalogue est écrite au journal à chaque chargement.
31. **Réponse falsifiée en chemin ?** → Signature invalide : refus et ligne d'alerte.
32. **Demande envoyée deux fois ?** → Même identifiant de demande : une seule exécution, même résultat.
33. **Wifi coupé ?** → Tout tourne en local, réseaux Docker sans Internet ; images sauvegardées hors ligne.
34. **« Casier vierge » et « registre injoignable », c'est pareil ?** → Non : vierge = réponse signée « oui » ; injoignable = « indisponible », non signé, rien n'est deviné.

**Données du jury**

35. **Votre OCR peut lire un 8 à la place d'un 3 dans une date : que se passe-t-il ?** → Un mot lu avec moins de 80 % de confiance laisse la case vide, donc refus. Une erreur lue avec assurance reste possible : le CSV produit est relu à deux avant usage, et son empreinte relie chaque réponse au PDF d'origine.
36. **Pas d'identifiant commun entre les registres ?** → Clé composée (nom + prénoms + date de naissance, éventuellement lieu), comparaison exacte sans accents ni majuscules ; plusieurs fiches = refus « homonymes ». Jamais de rapprochement approximatif.
37. **L'API du jury en direct : vos registres sortent sur le réseau ?** → Non. Par défaut, export unique avec empreinte. Sinon, un relais est le seul conteneur relié au réseau et ne parle qu'à l'adresse écrite dans la configuration ; API coupée = « indisponible ».

**Réutilisation**

38. **Un autre ministère peut-il s'en servir ?** → Ajouter une démarche = un bloc YAML ; brancher un registre = un fichier YAML. Les règles du socle sont adoptables même sans notre code (`docs/REGLES_DU_SOCLE.md`).
39. **En production ?** → Médiateur ouvert aux seuls systèmes autorisés, avec TLS mutuel, plus le jeton de l'agent. Feuille de route : SD-JWT, X-Road, vrai USSD, identifiant unique électronique, consentement du représentant légal.
40. **Qu'est-ce qui est simulé ?** → Les registres (données fictives), la connexion des usagers (numéro + PIN de démo), l'USSD (page web qui imite un téléphone). Voir `LIMITES.md`.

## Le parcours en une minute (passeport)

1. **Aujourd'hui**, pour un passeport ordinaire (passeport AES produit par l'ONI), l'usager apporte acte de
   naissance, certificat de nationalité, CNIB et extrait de casier, en copies légalisées.
2. **Avec Griot Secure**, l'agent des passeports (`moussa.kone`) choisit « Passeport ordinaire » et tape
   l'identifiant de l'usager. Il ne peut rien demander d'autre que ce que prévoit le catalogue.
3. Le **médiateur** interroge **en parallèle** deux registres : nationalité (« burkinabè ? ») et casier
   (« interdiction de sortie du territoire ? »). Pas l'état civil : l'ONI connaît déjà l'âge par la CNIB.
4. Chaque registre calcule la réponse **chez lui** et la **signe** avec sa clé. Il ne renvoie jamais la fiche.
5. **Vous voyez avant** : sur son téléphone (`*226#`), l'usager lit « L'ONI (passeports) recevra : burkinabè = oui ;
   interdiction de sortie du territoire = non. Rien d'autre. » et choisit Confirmer ou Refuser.
6. L'agent reçoit les deux réponses signées et le guichet **revérifie lui-même** chaque signature.
7. **Vous vérifiez après** : « Qui a consulté mes données » montre chaque consultation (qui, quand, pourquoi, sur
   quelle base), avec un **reçu** de 16 caractères vérifiable dans le journal.

## Les mécanismes, simplement

- **Signature (Ed25519, bibliothèque PyJWT)** : le registre signe avec sa clé privée, que lui seul possède. Tout le
  monde vérifie avec sa clé publique. Si le médiateur changeait « non » en « oui », la signature ne correspondrait
  plus : il ne peut **ni lire la fiche, ni fabriquer une réponse**.
- **Journal chaîné (SHA-256)** : chaque ligne contient l'empreinte de la précédente ; modifier une ligne casse la
  chaîne à cet endroit (`verifier.py` dit « Ligne N modifiée »). Le journal note le **fait**, jamais la **valeur**.
  Le citoyen y est pseudonymisé (HMAC).
- **Reçu** : les 16 premiers caractères de l'empreinte de la ligne. Un journal réécrit ne retrouve plus les reçus
  déjà donnés.
- **Double trace** : chaque registre garde chez lui la liste des réponses qu'il a signées ; `verifier.py
  --registres` la compare au journal.
- **Double clé** : le catalogue dit qui peut demander quoi, et chaque registre le revérifie lui-même (service,
  seuils d'âge), avec le jeton Keycloak de l'agent.
- **Règle d'or** : en cas de doute, on refuse. « Rien n'a été deviné. »
