# Limites (faits bruts, complétés au fil de la finale)

## Ce qui est simulé

- **Registres** : `registres_sim/`, données fictives (`registres_sim/donnees_fictives/`), en attendant les données du jury.
- **Connexion des usagers** : USSD simulé, numéro + PIN fictifs (`ussd_sim/abonnes.yaml`, PIN en clair pour la démo).
  En production : connexion par l'identifiant unique électronique.
- **Textes de loi** des démarches : références à faire valider (voir `catalogue/`).

## Règles de données à confirmer

- **Personne absente du casier** : le vrai casier ne contient que les condamnations ; une personne jamais condamnée
  n'y figure pas. Réglable dans `adaptateurs/casier.yaml` :
  - `absence: refus` (par défaut) : absent → « réponse impossible » (on ne devine pas) ;
  - `absence: vierge` : absent → « casier vierge », **après** vérification par le médiateur, à l'état civil, que la
    personne existe (une seule fiche, vivante). Sinon : « identité non confirmée ». État civil en panne : « identité non
    vérifiable, rien n'a été deviné ».
  Limite de `vierge` : on suppose que l'identifiant du casier est le même que celui de l'état civil.
- **Double nationalité** : la façon dont le registre de la nationalité l'écrit est inconnue (voir `docs/A_TRANCHER_DONNEES_JURY.md`).

## Ce que voit le médiateur

- La réponse minimale signée (ex. « nationalité burkinabè : oui »), gardée en attente jusqu'au consentement, puis effacée.
- Jamais la fiche, jamais la date de naissance, jamais le détail du casier.

## Ce qui n'est pas protégé

- « Registre indisponible » n'est pas signé (par définition, le registre n'a pas répondu).
- Supprimer la **dernière** ligne du journal n'est pas détectable par la chaîne seule : il faut un reçu remis à l'usager
  ou une ancre externe.
