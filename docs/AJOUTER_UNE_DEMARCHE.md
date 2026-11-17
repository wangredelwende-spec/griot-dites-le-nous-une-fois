# Ajouter une démarche en 2 minutes, sans toucher au code

Scène de démonstration « Adapter » : une administration ajoute une démarche en éditant **un fichier YAML**.

## 1. Écrire la démarche (1 minute)

Ajouter un bloc à la fin de `consentement-minimisation/catalogue/demarches.yaml`, par exemple :

```yaml
  inscription-universite:
    libelle: Inscription à l'université (bourse d'études)
    services: [service-bourses]
    finalite: vérification des conditions de la bourse d'études
    base: consentement                  # l'usager verra l'aperçu et confirmera sur *226#
    attributs:
      - attribut: age_entre
        parametres: {min: 17, max: 25, date_reference: "2026-10-01"}
        libelle: âge de 17 à 25 ans au 01/10/2026
      - attribut: nationalite_bf
        libelle: nationalité burkinabè
```

À retenir :
- `base: base_legale` exige `texte:`, c'est-à-dire le texte qui autorise la consultation sans accord.
- Les attributs possibles sont ceux que **les registres déclarent** dans `registres/adaptateurs/<registre>.yaml` :
  `age_entre` (paramètres `min`, `max` facultatif, `date_reference` : une date ou `aujourd'hui`),
  `nationalite_bf`, `casier_vierge` et `interdiction_sortie_territoire`.
- Facultatif, pour le guichet : `attendu: false` quand la bonne réponse est « non » (interdiction de sortie du
  territoire), et `si_non:` pour le texte montré quand la réponse est « non » (repli casier du passeport : « casier
  non vierge : dossier à instruire »). Une réponse « non » n'est jamais un refus : c'est une réponse signée.
- On ne peut pas demander « la date de naissance » : aucun registre ne la déclare.
- Facultatif, pour l'USSD : `finalite_mos:` (la finalité en mooré). Le mooré n'est proposé sur *226# que si
  **toutes** les démarches du catalogue ont leur `finalite_mos` ET si `phrases-ussd.csv` est complet en mooré :
  ajouter une démarche sans `finalite_mos` retire donc le mooré jusqu'à ce qu'elle soit traduite.

## 2. Recharger : rien à faire (quelques secondes)

Enregistrer le fichier suffit : le médiateur le relit dès la requête suivante (au plus une fois par seconde),
**sans redémarrage**, et le guichet affiche le catalogue que le médiateur applique. Pour voir ce qui s'est passé :

```powershell
docker compose logs mediateur --tail 5
```

- Si la nouvelle version est **invalide** (YAML cassé ; finalité, base ou texte manquant ; attribut inconnu comme la
  date de naissance ; service ou seuil refusé par la double clé d'un registre), elle est **refusée** : le médiateur
  **garde l'ancien catalogue et continue de tourner**. La raison s'affiche en haut du guichet et sur la page Contrôle,
  et une ligne « catalogue refusé » entre au journal. Exemple : `démarche « inscription-universite » : base légale sans
  texte cité`. Corriger et enregistrer : la version corrigée est prise.
- Le dernier catalogue valide est aussi copié dans le volume du médiateur : même un redémarrage avec un fichier
  invalide repart de cette copie au lieu de s'arrêter.
- Sinon, la démarche apparaît au guichet des agents du service. L'**empreinte SHA-256** du nouveau catalogue est écrite
  dans le journal chaîné : on peut prouver quelles règles étaient en vigueur lors de chaque consultation.

## 3. La double clé : l'accord du registre

Le registre décide aussi du **mode** : dans `bases:` de son YAML, il déclare pour chaque service s'il accepte le
**consentement** (`consentement: true`) et/ou la **base légale**, avec la liste des références de textes acceptées
(`base_legale: ["loi n°081-2015/CNT"]`). Une démarche en base légale n'est acceptée que si son `texte:` contient
l'une de ces références. Sinon : refus au chargement du catalogue (le médiateur garde l'ancien) **et** refus signé
du registre lui-même (« base juridique non autorisée par le registre pour ce service »). Exemple : passer le
passeport en `base: base_legale` est refusé, car la nationalité et le casier n'ont déclaré que le consentement
pour le service passeport.

Le catalogue ne suffit pas : **chaque registre décide lui-même**, dans `registres/adaptateurs/<registre>.yaml`,
quels services peuvent lui demander quel attribut, **et avec quels paramètres**. Pour l'exemple ci-dessus,
l'état civil doit ajouter les seuils du service des bourses :

```yaml
# registres/adaptateurs/etat-civil.yaml, attribut age_entre
    services:
      service-bourses:
        - {min: 18, date_reference: aujourd'hui}
        - {min: 17, max: 25, date_reference: "2026-10-01"}    # bourse d'études (ajout)
```

puis `docker compose restart registre-etat-civil`.

Sans cet ajout, le médiateur **refuse la nouvelle version du catalogue** (raison affichée au guichet) ; et si
quelqu'un passait outre, le registre **refuserait lui-même**, par une réponse signée : « paramètres non autorisés par le registre pour ce service »
(ou « service non autorisé par le registre à demander cet attribut »). Pourquoi les paramètres ? Sans cette règle,
un service pourrait poser « 25 ans ? 26 ans ? 27 ans ?… » et reconstituer la date de naissance.

Le registre vérifie aussi **lui-même** qui demande : le médiateur lui transmet le jeton Keycloak de l'agent, et le
registre en contrôle la signature (clés publiques de Keycloak), l'expiration et le groupe (= le service).
Un médiateur compromis ne peut donc pas se faire passer pour un autre service.

Pour autoriser un nouveau service, il faut l'accord des deux côtés : le catalogue (le médiateur)
**et** l'adaptateur du registre (l'administration qui détient la donnée). Chaque registre ne monte que SON
adaptateur ; le médiateur et le guichet les lisent en lecture seule et ne peuvent pas les modifier.
