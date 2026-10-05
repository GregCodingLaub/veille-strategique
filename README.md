# Veille stratégique

Collecte quotidienne de publications (flux RSS, pages web, comptes Bluesky), filtrage par mots-clés, puis trois newsletters hebdomadaires et un site statique.

| Newsletter | Contenu |
|---|---|
| Renseignement & Intelligence économique | services, OSINT, contre-ingérence, guerre économique |
| Défense & Industrie militaire | conflits, forces armées, industrie d'armement, dissuasion |
| Énergie & Infrastructures | énergie, minerais critiques, gazoducs, câbles sous-marins et optiques, data centers, satellites, points de passage stratégiques, sous l'angle géopolitique (pas de technique) |

## Fonctionnement

- **Chaque jour, 06:00 UTC** : `scripts/fetch.py` collecte, nettoie, filtre et classe (thème + zone) les publications dans `data/items.json`, et note l'état de chaque source dans `data/source_health.json`.
- **Chaque lundi** : la même exécution envoie les trois newsletters (envoi officiel : vous + abonnés, calendrier enregistré). Un thème sans nouveauté n'est pas envoyé.
- **Exécution manuelle** (Actions > Veille Stratégique > Run workflow), champ `mode` :
  - `test` (défaut) : collecte + envoi de test à vous seul, objet `[TEST]`, calendrier et archive des éditions intacts ;
  - `fetch` : collecte seule ;
  - `official` : envoi officiel immédiat.
- Le site `docs/index.html` est régénéré à chaque exécution.

## Fichiers à éditer

- `sources.yaml` : les sources et leurs options (`enabled`, `default_themes`, `initial_limit`, `stale_after_days`, `max_pages`, `require_report`…).
- `keywords.yaml` : mots-clés par thème et exclusions techniques. Correspondance par mot entier, sans accent ni casse, pluriels tolérés.
- `regions.yaml` : zone d'un article (le sujet traité) ; sans correspondance, la zone de l'institution.

Après toute modification : `python scripts/check_config.py` puis, pour réappliquer les règles à l'archive, `python scripts/backfill_items.py` (aperçu) ou `--apply`.
`python scripts/validate_sources.py [nom]` teste les sources en direct (réseau requis).
Tests : `pip install pytest && pytest`.

## Secrets GitHub

| Secret | Rôle |
|---|---|
| `RESEND_API_KEY`, `RESEND_TO_EMAIL`, `RESEND_FROM_EMAIL` | envoi (Resend) |
| `SITE_URL` | URL GitHub Pages (liens des emails) |
| `RECIPIENTS_CSV_URL` | CSV publié de la Google Sheet des abonnés |
| `SIGNUP_FORM_URL` | formulaire d'inscription (bouton du site, lien de désabonnement) |

## Ouverture à des tiers : points de vigilance

1. **Domaine d'envoi vérifié obligatoire.** Avec `onboarding@resend.dev`, Resend ne livre qu'au propriétaire du compte : les abonnés ne sont alors pas contactés (avertissement dans les logs). Vérifier un domaine sur resend.com/domains.
2. **Limite gratuite** : 100 emails par jour. Chaque abonné reçoit un message individuel par thème choisi ; le script avertit au-delà de 90.
3. **Désabonnement** : ajouter l'option « Me désabonner » aux cases « Thèmes » du formulaire ; la dernière réponse d'une adresse prévaut. Le lien du pied d'email pointe vers le formulaire.
4. **Pas de double opt-in** : n'importe qui peut saisir l'adresse d'un tiers. À accepter pour un cercle de pairs, à traiter avant tout élargissement.
5. **CSV public** : le lien publié de la feuille donne accès aux adresses à qui le possède. Garder le lien secret.
6. **Alertes sources** : chaque envoi vous écrit si une source est en erreur, vide ou muette depuis longtemps.

## Scrapers (IFRI, CSIS, CIA)

Sans flux RSS, ces sources passent par `scripts/scrapers.py`, écrit à partir des motifs d'URL et de dates visibles dans les pages. Si une source devient vide, l'alerte hebdomadaire le signale ; ajuster alors le parseur.
