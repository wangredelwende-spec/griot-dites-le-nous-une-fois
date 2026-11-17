# Ajouter une démarche en 2 minutes, sans toucher au code

Scène de démonstration « Adapter » : une administration ajoute une démarche en éditant **un fichier YAML**.

## 1. Écrire la démarche (1 minute)

Ajouter un bloc à la fin de `consentement-minimisation/catalogue/demarches.yaml`, par exemple :



```yaml

  agrement-commercial:

    libelle: Agrément d'une activité commerciale

    services: [cefore]

    finalite: instruction d'une demande d'agrément d'activité commerciale

    base: consentement                  # l'usager verra l'aperçu et confirmera sur *226# ou sur le portail

    duree_accord_heures: 48

    attributs:

      - attribut: casier_vierge

        libelle: casier judiciaire vierge

```



À retenir :
- `base: base_legale` exige `texte:`, c'est-à-dire le texte qui autorise la consultation sans accord.
- Les attributs possibles sont ceux déclarés dans `consentement-minimisation/catalogue/attributs.yaml` : `majeur`

  (paramètres `min`, `max` facultatif, `date_reference` : une date ou `aujourd'hui`), `nationalite_bf`, `casier_vierge`,

  `identite` et `naissance_filiation`. Pour chacun : quel registre le fournit, comment la passerelle le calcule,

  et **quels services ont le droit de le demander** (et, pour `majeur`, avec quels seuils).

- On ne peut pas demander « la date de naissance » : aucun registre ne la déclare.
- Facultatif, pour l'USSD : `finalite_mos:` (la finalité en mooré). Le mooré est **arrêté** (aucune langue complète) :

  aucun choix de langue n'est proposé, l'écran reste en français.



## 2. Recharger : rien à faire (quelques secondes)

Enregistrer le fichier suffit : le médiateur le relit dès la requête suivante (au plus une fois par seconde),
**sans redémarrage**, et le guichet affiche le catalogue que le médiateur applique. Pour voir ce qui s'est passé :

```powershell
docker compose logs mediateur --tail 5
```

- Si la nouvelle version est **invalide** (YAML cassé ; finalité, base ou texte manquant ; attribut inconnu comme la
  date de naissance ; service ou seuil non autorisé dans `attributs.yaml`), elle est **refusée** : le médiateur
  **garde l'ancien catalogue et continue de tourner**. La raison s'affiche en haut du guichet et sur la page Contrôle,
  et une ligne « catalogue refusé » entre au journal. Exemple : `démarche « inscription-universite » : base légale sans
  texte cité`. Corriger et enregistrer : la version corrigée est prise.
- Le dernier catalogue valide est aussi copié dans le volume du médiateur : même un redémarrage avec un fichier
  invalide repart de cette copie au lieu de s'arrêter.
- Sinon, la démarche apparaît au guichet des agents du service. L'**empreinte SHA-256** du nouveau catalogue est écrite
  dans le journal chaîné : on peut prouver quelles règles étaient en vigueur lors de chaque consultation.

## 3. Les trois fichiers : annuaire.yaml, attributs.yaml, demarches.yaml



Une démarche touche jusqu'à trois fichiers de `consentement-minimisation/catalogue/` (aucun code) :



| Fichier | Ce qu'on y écrit | Quand |

|---|---|---|

| `annuaire.yaml` | le **service** demandeur (`groupe` Keycloak, nom, empreinte de sa clé API) | nouvelle administration seulement |

| `attributs.yaml` | l'**autorisation** : sous `services:` de l'attribut, le nouveau service (et, pour `majeur`, ses seuils autorisés) | si le service n'a pas encore le droit de demander cet attribut |

| `demarches.yaml` | la **démarche** : libellé, services, finalité, base, attributs | toujours |



C'est la **double clé** de la passerelle : une démarche qui demande ce que son service n'a pas le droit d'obtenir est

**refusée au chargement** (« attributs.yaml n'autorise pas … »), le catalogue en vigueur reste en place. Exemple pour

que la mairie demande la nationalité : ajouter le service `mairie` dans `annuaire.yaml`, `mairie` à la liste `services`

de `nationalite_bf` dans `attributs.yaml`, puis la démarche dans `demarches.yaml` (test :

`consentement-minimisation/tests/test_catalogue.py::test_nouvelle_administration_par_configuration_seule`).

Pour `majeur`, les seuils sont aussi autorisés par service : sans cela, un service pourrait poser « 25 ans ? 26 ans ?

27 ans ?… » et reconstituer la date de naissance.



Limite : depuis le 17/11, les registres n'ont plus de double clé de leur côté (ils répondent à qui les appelle sur le

réseau `registres`) : voir `LIMITES.md`. Le nouveau groupe Keycloak de l'agent doit exister (`scripts/keycloak_groupes_cadre.py`).

