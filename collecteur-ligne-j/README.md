# Collecteur ligne J — Vernouillet-Verneuil → Paris Saint-Lazare

Relève toutes les 5 minutes, les matins de semaine, les trains de la ligne J
au départ de Vernouillet-Verneuil vers Paris Saint-Lazare : heure prévue, heure
réelle au départ et à l'arrivée, suppressions annoncées, messages d'info trafic.
Source : API « Prochains passages » de PRIM (Île-de-France Mobilités).

Un fichier par jour dans `data/AAAA-MM-JJ.json`.

## Mise en route

1. Créez un compte sur https://prim.iledefrance-mobilites.fr, puis une clé API
   (menu « Mes jetons d'authentification »). Abonnez-vous aux API
   « Prochains passages (plateforme Île-de-France Mobilités) – requête unitaire »
   et « Messages Info Trafic – requête unitaire » si le site le demande.
2. Créez un dépôt GitHub **public** (les minutes GitHub Actions y sont gratuites)
   et déposez-y ce dossier tel quel, y compris `.github/workflows/collect.yml`.
3. Dans le dépôt : Settings → Secrets and variables → Actions → New repository
   secret. Nom : `PRIM_API_KEY`, valeur : votre clé.
4. Onglet Actions → « Collecte ligne J » → Run workflow, pour un premier essai.
   Le journal doit afficher « N trains suivis ». La collecte tourne ensuite seule.

Si le journal dit « Arrêt introuvable », ajoutez dans Settings → Secrets and
variables → Actions → onglet Variables : `VERNOUILLET_REF` (et `LAZARE_REF`) au
format `STIF:StopArea:SP:NNNNN:`.

## Limites

- Les trains supprimés la veille n'apparaissent pas dans le temps réel : ils
  manquent simplement. La page les repère en comparant chaque jour à la grille
  habituelle observée.
- GitHub peut retarder les tâches planifiées de quelques minutes ; l'API
  annonçant les trains à l'avance, cela ne fait pas perdre de train.
