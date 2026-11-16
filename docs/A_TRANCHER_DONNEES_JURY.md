# Points à trancher dès l'arrivée des données du jury

À vérifier sur les fichiers de `donnees_jury/` (jamais commités), puis à régler dans `adaptateurs/*.yaml` sans changer le code.

| Point | Question | Réglage |
|---|---|---|
| Identifiant commun | Les 3 registres partagent-ils un identifiant ? Sinon, comment rapprocher les fiches ? | `identite:` de chaque adaptateur |
| Absence du casier | Le casier fourni liste-t-il tout le monde, ou seulement les condamnés ? | `absence: refus` ou `absence: vierge` (`adaptateurs/casier.yaml`) |
| Double nationalité | Comment est-elle écrite ? (« burkinabe;ivoirienne », deux lignes, une colonne par nationalité…) | règle de `adaptateurs/nationalite.yaml` (aujourd'hui : valeur exactement égale à « burkinabe ») |
| Dates incomplètes | Quels formats ? (« vers 1990 », « 1990 », « 00/00/1990 »…) | `bornes_de_naissance` (refus si on ne peut pas conclure) |
| Décès | Où est noté le décès ? | `champs.date_deces` + `refuser_si_decede` |
| Homonymes, doublons | Même identifiant pour deux fiches ? | refus « identité ambiguë » (déjà en place) |
