# suivi-vols

Un outil 100 % gratuit qui relève chaque jour les prix des vols qui t'intéressent, t'envoie une
notification sur ton téléphone quand quelque chose d'important se passe, et publie un petit site
avec les courbes de prix.

- **Source des prix** : l'API Google Flights de [SerpApi](https://serpapi.com/google-flights-api)
  (forfait gratuit : 250 recherches par mois).
- **Exécution** : GitHub Actions, tous les jours à 11:00 UTC (gratuit pour un dépôt public).
- **Site** : GitHub Pages.
- **Notifications** : [ntfy](https://ntfy.sh), gratuit et sans compte.

---

## Sommaire

1. [Mise en route (une seule fois)](#1-mise-en-route-une-seule-fois)
2. [Ajouter un voyage](#2-ajouter-un-voyage)
3. [Exclure une combinaison de dates](#3-exclure-une-combinaison-de-dates)
4. [Renseigner le prix d'achat](#4-renseigner-le-prix-dachat)
5. [Lancer à la main](#5-lancer-à-la-main)
6. [Installer ntfy sur le téléphone](#6-installer-ntfy-sur-le-téléphone)
7. [Lire le tableau de bord et la page Analyse](#7-lire-le-tableau-de-bord-et-la-page-analyse)
8. [Comment le budget est protégé](#8-comment-le-budget-est-protégé)
9. [Les fichiers du projet](#9-les-fichiers-du-projet)

---

## 1. Mise en route (une seule fois)

### a) Créer le dépôt sur GitHub
1. Sur github.com : **New repository**. Nom : `suivi-vols`. Visibilité : **Public**.
   GitHub Pages gratuit exige un dépôt public. Tes prix seront donc visibles, mais **tes clés restent
   secrètes**. Avec le *GitHub Student Developer Pack* (GitHub Pro gratuit pour les étudiants),
   tu peux aussi mettre le dépôt en privé.
2. Sur la page du dépôt vide : **uploading an existing file**. Glisse **tout le contenu** du dossier
   `suivi-vols` (y compris le dossier caché `.github`), puis **Commit changes**.
   > Sous Windows, l'Explorateur cache parfois les dossiers qui commencent par un point. Vérifie
   > après l'envoi que `.github/workflows/daily.yml` est bien présent dans le dépôt. Sinon, crée-le
   > à la main : **Add file → Create new file**, nom `.github/workflows/daily.yml`, puis colle le contenu.

### b) Ajouter les deux secrets
**Settings → Secrets and variables → Actions → New repository secret** :

| Nom | Valeur |
|---|---|
| `SERPAPI_API_KEY` | ta clé, sur https://serpapi.com/manage-api-key |
| `NTFY_TOPIC` | un nom de « sujet » ntfy **long et impossible à deviner**, par ex. `vols-quentin-7f3k9q2x` (voir §6) |

Ne colle jamais ces valeurs ailleurs (ni dans un fichier, ni dans une conversation).

### c) Activer le site
**Settings → Pages → Build and deployment → Source : GitHub Actions.**

### d) Renseigner la date de renouvellement du quota
Dans `config.yaml`, champ `renewal_date`. Tu trouves cette date sur ton tableau de bord SerpApi.
Si tu la laisses vide, l'outil la lit lui-même auprès de SerpApi.

### e) Premier lancement (dès aujourd'hui)
1. Onglet **Actions** → **Collecte quotidienne** → **Run workflow**, en cochant **Simulation**.
   Rien n'est consommé : tu vois dans le journal combien de recherches sont prévues et la
   projection du budget.
2. Si tout te paraît correct, relance **sans** cocher Simulation : c'est la vraie première collecte.
3. Quand c'est vert, ton site est à l'adresse `https://TON-PSEUDO.github.io/suivi-vols/`.
   Copie cette adresse dans `config.yaml` (`alerts.site_url`) : un clic sur une notification
   ouvrira alors le site.

Ensuite, tout se fait seul chaque jour à 11:00 UTC. GitHub peut décaler le lancement de quelques
minutes, voire d'une heure les jours chargés : c'est normal.

> **Modifier un fichier directement sur GitHub** : ouvre le fichier, clique sur le crayon ✏️,
> modifie, puis **Commit changes**. Toutes les opérations ci-dessous se font comme ça.

---

## 2. Ajouter un voyage

Dans `trips.yaml`, copie le bloc complet de `noel-2026` (de `- id:` jusqu'à `excluded_combinations`)
et colle-le en dessous. Change au minimum :

- `id` : court, unique, sans espace (`ete-2027`) ;
- `name`, `origin`, `destination` ;
- `outbound_options` / `return_options` : les dates possibles et, si tu veux, `depart_after`
  ou `depart_before` (`"HH:MM"`) ;
- `purchase_deadline`, `tracking_start` (le jour où tu commences le suivi) ;
- `purchase` : `price: null`, `date: null`.

**Voyage en aller simple uniquement** : laisse `return_options: []`.

**Prix cible** : `target_price: auto` pour utiliser le bas de la fourchette typique de Google,
recalculé chaque jour. Mets un nombre (`target_price: 850`) pour un montant fixe.
Google ne fournit pas toujours cette fourchette (c'est le cas pour `noel-2026` avec les filtres
vol direct + bagage + horaire). Dans ce cas, `auto` se replie sur **`target_fallback_pct` % sous
le meilleur prix observé les jours précédents** (5 % par défaut ; `0` désactive le repli).
L'alerte « prix cible atteint » signifie alors : « un prix vient de battre nettement le record ».

**Phases**, pour un voyage suivi longtemps à l'avance :

```yaml
phases:
  exploration_days: 7        # les 7 premiers jours : tout, chaque jour
  watch_every_days: 3        # ensuite, une recherche tous les 3 jours…
  watch_combinations: best   # …seulement sur les meilleures combinaisons (ou "all", ou une liste)
  decision_days: 10          # les 10 derniers jours avant la date limite : tout, chaque jour
```

Avant d'enregistrer, compte combien de recherches ton nouveau voyage demandera :
**(nombre de combinaisons) + (dates aller + dates retour, si allers simples) + 1 (détail du retour)**
par jour de collecte. Les voyages se partagent les 240 recherches du cycle : si ça ne tient pas,
l'outil réduit automatiquement (voir §8). Pour vérifier, lance une **Simulation** (§5).

## 3. Exclure une combinaison de dates

Dans `trips.yaml`, sous le voyage :

```yaml
excluded_combinations: ["2026-12-17_2027-01-06"]
```

Le format est `ALLER_RETOUR`. La section **Suggestions** du site te propose des candidates :
les combinaisons jamais à moins de 10 % du minimum du jour (seuil réglable dans `config.yaml`).
Elle signale aussi quand les allers simples ne battent jamais l'aller-retour : tu peux alors
mettre `one_way: false` dans `modes`. **Rien n'est exclu automatiquement.**

## 4. Renseigner le prix d'achat

Quand tu as acheté :

```yaml
purchase:
  price: 1012.45
  date: "2026-11-15"
```

Dès le prochain lancement, ce voyage n'est plus recherché et ne consomme plus rien. Le prix payé
apparaît sur la page Analyse, comparé au minimum observé.

Si la date limite passe **sans** prix d'achat, l'outil continue en **mode réduit**
(aller-retour seulement, chaque jour, jusqu'au départ). Pour tout arrêter, mets `after_deadline: stop`.

## 5. Lancer à la main

**Actions → Collecte quotidienne → Run workflow.**

- **Simulation** cochée : affiche le plan du jour et la projection du budget, **zéro recherche consommée**.
- Sans simulation : vraie collecte. Relancer le même jour **ne refait pas** les recherches déjà
  réussies. Seules celles qui ont échoué sont retentées. Les lancements manuels respectent
  exactement le même plafond que les lancements automatiques.

Sur ton ordinateur (facultatif, Python 3.10 ou plus) :

```bash
pip install -r requirements.txt
```

```bash
python src/fetch_prices.py --dry-run
```

```bash
python -m unittest discover tests
```

Les tests utilisent de fausses réponses : ils ne consomment rien et n'ont pas besoin de clé.

## 6. Installer ntfy sur le téléphone

1. Installe l'application **ntfy** (Google Play, F-Droid ou App Store). Elle est gratuite, sans compte.
2. Ouvre-la → **+** → **S'abonner à un sujet** → tape **exactement** la même valeur que ton secret
   `NTFY_TOPIC` → **S'abonner**.
3. Sur iPhone, autorise les notifications quand l'application le demande.

N'importe qui connaissant le nom du sujet peut lire tes notifications : choisis un nom long et
aléatoire, et ne le partage pas.

Alertes envoyées :

| Alerte | Quand |
|---|---|
| Premier prix / nouveau minimum | le prix le plus bas du voyage baisse |
| Prix cible atteint | un prix passe sous la cible (puis à nouveau seulement s'il baisse encore) |
| Deux allers simples moins chers | la première fois que ça arrive pour une combinaison |
| Date limite | 7 jours avant, puis 1 jour avant |
| Budget réduit | quand l'outil doit réduire les recherches pour tenir le quota |

## 7. Lire le tableau de bord et la page Analyse

### Tableau de bord
- **Filtres** (en haut) : voyage, combinaison, mode, compagnie, heure de départ de l'aller,
  période de recherche. Ils s'appliquent à la courbe, au tableau croisé et au tableau des options.
- **Meilleur choix actuel** : le prix le plus bas du dernier relevé, avec un verdict.
  - **Acheter** : prix ≤ prix cible, ou date limite aujourd'hui ou demain, ou prix proche du
    minimum avec une date limite à moins de 7 jours.
  - **Surveiller** : à moins de 5 % du prix cible, ou date limite à moins de 7 jours.
  - **Attendre** : sinon.
  C'est une aide à la décision, pas une garantie : Google peut changer ses prix à tout moment.
- **Courbe** : une ligne par combinaison, le minimum du jour en pointillé, la fourchette typique
  de Google en gris (quand une seule combinaison est choisie), et la date limite en trait vertical.
- **Tableau croisé** : chaque case donne le prix d'une combinaison de dates un jour de recherche donné.
- **Quota** : recherches utilisées, fin du cycle, mode de réduction en cours.

### Page Analyse
Elle mélange tous tes voyages pour repérer des tendances. Les prix n'ont pas la même échelle d'un
voyage à l'autre : chaque prix est donc exprimé en **% au-dessus du minimum observé** pour sa
combinaison de dates (0 % = le meilleur prix vu).

- **Jours avant le départ** : à quelle distance du départ les prix étaient les plus bas.
- **Jour de la semaine de recherche** : vérifie si « chercher le mardi » aide vraiment.
- **n** = nombre d'observations. **Sous 20, la barre est grisée** : ne tire pas de conclusion.
  Avec un seul voyage, ces chiffres décrivent surtout ce voyage-là. Ils deviennent intéressants
  après plusieurs voyages.
- **Prix payé vs minimum** : l'écart entre ce que tu as payé et le meilleur prix vu.

## 8. Comment le budget est protégé

- `data/usage.json` compte chaque recherche **avant** de l'envoyer. Le compteur est remis à zéro
  à la date de renouvellement.
- Avant chaque lancement, l'outil vérifie le vrai compteur chez SerpApi (API « Account », gratuite)
  et garde le plus prudent des deux.
- Il **projette** ensuite la consommation de tous les voyages actifs jusqu'au prochain
  renouvellement. Si elle dépasse ce qui reste, il réduit dans cet ordre :
  1. allers simples un jour sur deux ;
  2. plus de détail du vol retour ;
  3. seulement les meilleures combinaisons (`best_combinations_kept` dans `config.yaml`) ;
  4. en dernier recours, un nombre fixe de recherches par jour.

  Tu reçois une notification quand une réduction démarre.
- Dans tous les cas, aucune recherche n'est envoyée si elle ferait dépasser 240.

Ordre de grandeur pour `noel-2026` : 6 allers-retours + 5 allers simples + 1 détail = **12
recherches par jour** jusqu'au 20 novembre. Ensuite, 6 par jour en mode réduit jusqu'au départ.
Selon ta date de renouvellement, il est normal qu'une réduction se déclenche.

## 9. Les fichiers du projet

| Fichier | Rôle |
|---|---|
| `config.yaml` | réglages globaux (budget, heure, alertes) |
| `trips.yaml` | tes voyages |
| `src/fetch_prices.py` | collecte (lance les recherches et enregistre tout) |
| `src/build_site.py` | fabrique `site/data.json` à partir des CSV |
| `src/planner.py` | décide quelles recherches faire chaque jour |
| `src/budget.py` | compteur, projection, réductions |
| `src/serpapi_client.py`, `src/parse.py` | appel de SerpApi et lecture des réponses |
| `src/alerts.py`, `src/notify.py` | règles d'alerte et envoi ntfy |
| `data/searches.csv` | une ligne par recherche |
| `data/flights.csv` | une ligne par option de vol trouvée |
| `data/combos.csv` | comparaison aller-retour / deux allers simples, par combinaison et par jour |
| `data/price_history.csv` | historique de prix fourni par Google, quand il existe |
| `data/raw/AAAA-MM-JJ/*.json.gz` | réponses brutes de SerpApi (sans ta clé) |
| `data/usage.json`, `data/alerts_state.json` | compteur de recherches, alertes déjà envoyées |
| `site/` | le site (HTML/CSS/JS, sans framework ; Chart.js pour les courbes) |
| `.github/workflows/daily.yml` | l'automatisation quotidienne |

Les fichiers CSV ne sont **jamais réécrits** : on ajoute seulement des lignes à la fin.
Tu peux les ouvrir dans Excel ou Google Sheets.

### Paramètres SerpApi utilisés (vérifiés dans la doc officielle)
`engine=google_flights`, `type` (1 = aller-retour, 2 = aller simple), `departure_id`, `arrival_id`,
`outbound_date`, `return_date`, `stops=1` (sans escale), `outbound_times` / `return_times`
(ex. `20,23` = départ entre 20:00 et 23:59), `bags` (bagages cabine), `travel_class=1`, `adults`,
`currency`, `hl`, `gl`, `departure_token` (vols retour d'un aller choisi). `price_insights` n'est
pas un paramètre : c'est un bloc de la réponse (`lowest_price`, `price_level`,
`typical_price_range`, `price_history`), présent seulement quand Google le fournit.
