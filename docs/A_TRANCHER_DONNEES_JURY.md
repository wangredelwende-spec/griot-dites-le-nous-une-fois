# Points à trancher dès l'arrivée des données du jury

À vérifier sur les fichiers de `donnees_jury/` (jamais commités), puis à régler dans `registres/adaptateurs/*.yaml` sans changer le code.

| Point | Question | Réglage |
|---|---|---|
| Identifiant commun | Les 3 registres partagent-ils un identifiant ? Sinon, comment rapprocher les fiches ? | `identite:` de chaque adaptateur |
| Absence du casier | Le casier fourni liste-t-il tout le monde, ou seulement les condamnés ? | `absence: refus` ou `absence: vierge` (`registres/adaptateurs/casier.yaml`) . Attention, avec `absence: vierge`, une personne absente du casier n'est « vierge » qu'après confirmation de son identité par l'état civil (`personne_connue`), qui n'est autorisée qu'au concours : pour le **passeport**, elle reçoit donc toujours un **refus** « identité non confirmée » (testé : `passerelle/tests/test_passeport_absent_du_casier.py`). Pour l'accepter, l'état civil devrait déclarer `service-passeport` sur `personne_connue` (l'ONI apprendrait seulement « existe »). |
| Double nationalité | Comment est-elle écrite ? (« burkinabe;ivoirienne », liste JSON, deux lignes, une colonne par nationalité…) | « a ; b » et listes JSON : oui si l'une convient. Deux LIGNES pour une personne : aujourd'hui refus « identité ambiguë » (à décider) |
| Dates incomplètes | Quels formats ? (« vers 1990 », « 1990 », « 00/00/1990 »…) | `format_date` + `bornes_de_naissance` : « aaaa », « aaaa-mm » acceptés si concluants ; « 00/00/1990 » et « vers » : refus |
| Décès | Où est noté le décès ? | `champs.date_deces` + `refuser_si_decede` |
| Homonymes, doublons | Même identifiant pour deux fiches ? | refus « identité ambiguë » (déjà en place) |
| Valeurs écrites autrement | « Burkinabè », « BF », « BFA »… | `correspondances: {oui: […], non: […]}` ; valeur absente des deux listes : refus |
| Interdiction de sortie du territoire | Le casier du jury a-t-il une colonne de peines complémentaires ? | sinon : retirer `interdiction_sortie_territoire` du passeport et reprendre `casier_judiciaire_vierge` dans `consentement-minimisation/catalogue/demarches.yaml` |
| API du jury | Export ou API en direct ? | **Décidé (16/11)** : par défaut, **export unique** vers un fichier JSON avec empreinte SHA-256 (`scripts\exporter_api_jury.py`), puis registre `type: json`, sans réseau. Si le jury impose l'API en direct : profil `api-jury`, un **relais** seul à toucher le réseau, qui ne transmet qu'à `API_JURY_URL` (.env), en GET, délai 2 s ; le registre reste sans sortie (`JOUR_J_DONNEES_JURY.md`) |

## PDF scanné : plan B

1. Conversion **une seule fois** par le conteneur OCR (Tesseract, profil `ocr`, sans réseau) : `docs/JOUR_J_DONNEES_JURY.md`, étape 3 bis.
2. Une case dont un mot est reconnu avec une confiance < 80 reste **VIDE** → refus « donnée insuffisante ». Une ligne entièrement illisible disparaît (la personne sera « introuvable », donc refusée).
3. Empreintes SHA-256 du PDF d'origine et du CSV produit dans `<fichier>.provenance.json` : on peut prouver de quel PDF vient chaque réponse.
4. Si l'OCR échoue (tableau sans alignement, écriture manuscrite) : saisie manuelle d'un CSV par l'équipe, relue à deux, avec la même note de provenance. Jamais de correction « à l'œil » d'une case douteuse.
