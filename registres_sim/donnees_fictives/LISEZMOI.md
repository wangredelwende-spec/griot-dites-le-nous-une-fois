# Données fictives (en attendant les données du jury)

Personnes inventées, sans lien avec des personnes réelles. Cas pièges prévus (date de référence : 16/11/2026) :

| nip | Cas | Réponse attendue pour « majeur » |
|---|---|---|
| BF-0001 | adulte ordinaire | oui |
| BF-0003, BF-0017 | mineurs | non |
| BF-0004 | « vers 1990 » (date approximative) | refus : donnée insuffisante |
| BF-0005 / BF-0006 | homonymes (même nom et prénom, nip différents) | oui pour chacun : le nip les distingue |
| BF-0007 | personne décédée | refus : personne décédée |
| BF-0008 | casier non vierge (registre du casier, phase 2) | oui |
| BF-0009 | 18 ans le 20/11/2026, pendant la finale | non jusqu'au 19/11, oui à partir du 20/11 |
| BF-0010 | mois connu, jour manquant (2008-11) | refus : donnée insuffisante (ne permet pas de conclure) |
| BF-0011 | année seule (2004) | oui : même né le 31/12/2004, elle a 18 ans |
| BF-0019 | doublon (deux fiches pour le même nip) | refus : identité ambiguë |
| BF-0099 | absent du registre | refus : introuvable |

## Nationalité (`nationalite.csv`) et casier (`casier.csv`)

| nip | Nationalité burkinabè | Casier vierge |
|---|---|---|
| BF-0001 | oui | oui |
| BF-0003 | oui | refus : absente du casier (absent ≠ vierge) |
| BF-0005 | oui | non (1 condamnation) |
| BF-0006 | oui (naturalisation) | oui |
| BF-0008 | oui | **non** (2 condamnations : le détail ne sort jamais du registre) |
| BF-0013 | refus : nationalité non renseignée | oui |
| BF-0015 | oui | refus : nombre de condamnations vide |
| BF-0018 | **non** (ivoirienne) | oui |
