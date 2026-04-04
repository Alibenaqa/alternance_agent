# Alternance Agent — Agent IA Autonome de Recherche d'Alternance

Agent Python entièrement autonome qui scrape les offres d'alternance sur 8 plateformes, les score par IA, postule automatiquement, suit les réponses, relance les recruteurs, contacte des alumni et affiche tout sur un dashboard web — le tout piloté depuis Telegram.

Développé par **Ali Benaqa** — Bachelor Data & IA, Hetic (2e année — 3e année dès sept. 2026)

---

## Table des matières

- [Architecture globale](#architecture-globale)
- [Scrapers (8 sources)](#scrapers-8-sources)
- [Scoring IA (Claude Haiku)](#scoring-ia-claude-haiku)
- [Candidatures automatiques](#candidatures-automatiques)
- [LinkedIn Easy Apply (Playwright)](#linkedin-easy-apply-playwright)
- [Suivi des réponses & relances](#suivi-des-réponses--relances)
- [Calendrier iCloud](#calendrier-icloud)
- [Alumni Hetic (LinkedIn + Hunter.io)](#alumni-hetic-linkedin--hunterio)
- [Notifications Telegram](#notifications-telegram)
- [Dashboard web (Flask)](#dashboard-web-flask)
- [Persistance cloud (Turso)](#persistance-cloud-turso)
- [Déploiement Railway](#déploiement-railway)
- [Variables d'environnement](#variables-denvironnement)
- [Installation locale](#installation-locale)
- [Structure des fichiers](#structure-des-fichiers)

---

## Architecture globale

```
main.py
├── 8 Scrapers → SQLite (memory.py)
├── Scorer Claude Haiku → score 0.0–1.0
├── Alertes Telegram immédiates (offres >90%)
├── Candidatures auto (email domain-guess + formulaire WTTJ + LinkedIn Easy Apply)
├── Suivi réponses Gmail → analyse Claude → relances auto
├── Calendrier iCloud (entretiens → événement + rappel)
├── Alumni Hetic (DuckDuckGo → email domain-guess + Claude)
├── LinkedIn Agent (connexions, likes, commentaires, DMs — sessions autonomes)
├── Turso sync (persistance cloud entre redéploiements)
└── Dashboard Flask (auto-refresh 30s)
```

**Cycle automatique toutes les 4h :**
1. Restauration des candidatures depuis Turso (anti-doublon après redéploiement)
2. Scraping des 8 sources
3. Scoring Claude Haiku
4. Alerte immédiate offres ≥90%
5. Notification Telegram des offres intéressantes
6. Lecture des réponses recruteurs + relances auto
7. Candidatures automatiques (email/formulaire/Easy Apply)
8. Sync Turso
9. Outreach alumni Hetic

---

## Scrapers (8 sources)

### 1. Welcome to the Jungle (`scraper_wttj.py`)
- **Méthode :** API JSON officielle WTTJ
- **Couverture :** France entière (filtre IDF supprimé)
- **Mots-clés :** Data Analyst, Data Scientist, Data Engineer, ML, IA, MLOps, Fullstack, BI
- **Filtre :** contrat = alternance uniquement

### 2. LinkedIn (`scraper_linkedin.py`)
- **Méthode :** Endpoint public guest LinkedIn (sans compte)
- **URL :** `linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search`
- **Couverture :** France entière
- **Pagination :** infinie jusqu'à 0 résultat

### 3. Indeed (`scraper_indeed.py`)
- **Méthode :** Scraping HTML avec BeautifulSoup
- **Couverture :** France entière
- **Filtres :** 30 derniers jours, tri par date
- **Sélecteurs :** multiples fallbacks pour gérer les changements HTML

### 4. HelloWork (`scraper_hellowork.py`)
- **Méthode :** Scraping HTML avec BeautifulSoup
- **Filtre URL :** `?c=Alternance` (filtre contrat natif)
- **Couverture :** France entière
- **Pages :** jusqu'à 3 pages par mot-clé

### 5. La Bonne Alternance (`scraper_labonnealternance.py`)
- **Méthode :** API gratuite beta.gouv.fr, sans authentification
- **Codes ROME :** M1805, M1811, M1810, M1806 (dev, data, SI)
- **Rayon :** 300 km autour de Paris
- **Sources API :** `peJobs` (offres PE) + `matchas` (entreprises LBA)

### 6. France Travail (`scraper_france_travail.py`)
- **Méthode :** API officielle OAuth2 France Travail
- **Auth :** `client_credentials` → token Bearer
- **Type contrat :** `CA` (Contrat d'Apprentissage)
- **Couverture :** 18 départements (Paris, Lyon, Bordeaux, Lille, Strasbourg, Nantes, Nice, Rennes, Rouen…)
- **Credentials :** variables `FRANCE_TRAVAIL_CLIENT_ID` / `FRANCE_TRAVAIL_CLIENT_SECRET`

### 7. APEC (`scraper_apec.py`)
- **Méthode :** API interne APEC (non officielle mais stable)
- **Filtre :** contrat 204 (alternance), niveaux 634+631 (Bac+3 et Bac+2)
- **Pagination :** jusqu'à 3 pages par mot-clé → 90 offres max
- **Tri :** par date de publication

### 8. Alumni LinkedIn / DuckDuckGo (`alumni_linkedin.py`)
- Voir section [Alumni Hetic](#alumni-hetic-linkedin--hunterio)

---

## Scoring IA (Claude Haiku)

**Fichier :** `scorer.py`

Chaque offre nouvellement scrapée reçoit un score 0.0–1.0 via Claude Haiku.

### Critères de scoring

| Score | Signification |
|-------|--------------|
| 0.9–1.0 | Poste data/IA/dev, France, alternance, Bac+3 ou ouvert |
| 0.7–0.8 | Très bon match, quelques différences mineures |
| 0.5–0.6 | Match moyen, domaine adjacent |
| 0.0–0.4 | Hors domaine, trop senior, ou pas alternance |

### Bonus / Malus

| Règle | Impact |
|-------|--------|
| Mentionne explicitement Bac+3 ou Master 1 | +0.05 |
| Mentionne télétravail, remote, ou hybride | +0.05 |
| Exige Bac+4/5 ou Master 2 minimum | -0.10 |
| Pas une alternance (CDI/CDD/stage non confirmé) | -0.15 |
| Hors domaine (compta, RH non-data, marketing…) | -0.20 |

### Seuils
- **≥ 0.65** → statut `intéressant` → candidature possible
- **< 0.65** → statut `ignoré`
- **≥ 0.90** → alerte Telegram immédiate 🔥

### Batch
- 50 offres max par lancement (configurable `BATCH_SIZE`)
- Pause 0.5s entre chaque appel API

---

## Candidatures automatiques

**Fichier :** `candidater.py`

### Flux de candidature
1. Récupère les offres `intéressant` avec score ≥ 0.75
2. **Protection 1 :** vérification Turso (URL déjà postulée en cloud)
3. **Protection 2 :** même entreprise contactée dans les 30 derniers jours → skip
4. **Protection 3 :** URL normalisée en base locale
5. Tentative email via Hunter.io
6. Fallback formulaire WTTJ via Playwright
7. Notification Telegram pour chaque candidature

### Email de candidature (Claude Haiku)
- 130–160 mots, 3 paragraphes, ton humain et direct (pas de langue de bois)
- Adapté au TYPE de poste (Data → ETL/Power BI, IA → Claude API/agent, Dev → React/Node.js)
- Rebondit sur la description de l'offre (techno ou secteur mentionné)
- Cite des expériences concrètes : Techwin Services (ETL Python), Mamda Assurance (Power BI), BNC Corporation (KPI/EViews)
- Mots interdits : "je me permets de", "dynamique", "passionné", "opportunité", "n'hésitez pas à"
- Signature sobre + PS sur l'agent IA, CV joint en PDF

### Hunter.io
**Fichier :** `hunter.py`
- Recherche l'email du recruteur par nom de domaine de l'entreprise
- Retourne email + score de confiance
- Fallback si Hunter.io ne trouve rien → formulaire WTTJ

### Limites
- Max 10 candidatures par cycle (configurable `MAX_CANDIDATURES`)
- Score minimum 0.75 (configurable `SCORE_MIN_AUTO`)

---

## LinkedIn Easy Apply (Playwright)

**Fichier :** `linkedin_easy_apply.py`

### Fonctionnement
1. Connexion LinkedIn avec identifiants (gère les checkpoints de sécurité)
2. Récupère les offres LinkedIn score ≥ 0.75 pas encore postulées
3. **Vérification Turso anti-doublon** avant chaque candidature
4. Navigation vers l'offre, clic sur "Candidature simplifiée"
5. Remplissage automatique du formulaire multi-étapes :
   - Email, téléphone, prénom, nom, ville
   - Upload CV (`cv_ali.pdf`)
   - Questions texte → Claude Haiku génère une réponse courte
   - Textareas → Claude génère une réponse de motivation
   - Select dropdowns → première option non-vide
   - Radio buttons → coche "Oui" ou première option
6. Clic Submit, détection de la confirmation
7. Notification Telegram + enregistrement en base

### Anti-détection
- User-Agent Chrome 122
- Pauses aléatoires entre 1.5 et 6s
- Viewport 1280x800

### Limites
- Max 8 candidatures par cycle
- Requiert `cv_ali.pdf` présent dans le dossier
- Requiert `LINKEDIN_EMAIL` + `LINKEDIN_PASSWORD` en variables Railway

---

## Suivi des réponses & relances

**Fichier :** `reponses.py`

### Lecture des réponses recruteurs
- Connexion Gmail API OAuth2
- Lecture des emails non-lus depuis la boîte de réception
- Filtre par objet (mots-clés candidature/alternance)
- Analyse Claude Haiku pour chaque email :
  - **Type :** entretien / positif / négatif / en_attente / autre
  - **Urgence :** haute / normale / basse
  - **Suggestion de réponse** automatique
  - **Statut offre** mis à jour en base

### Détection entretien
- Regex pour extraire dates françaises : "15 avril 2026 à 14h00", "15/04/2026", "mercredi 22 avril"
- Si date trouvée → création événement iCloud automatique

### Relances automatiques
- Déclenchées 7 jours après une candidature sans réponse
- Maximum 2 relances par candidature
- Email de relance généré par Claude (ton professionnel et bienveillant)
- Bouton "Relancer maintenant" disponible sur Telegram via `/relances`

---

## Calendrier iCloud

**Fichier :** `calendrier.py`

### Fonctionnement
- Protocole CalDAV via requêtes HTTP directes (PROPFIND + PUT)
- Découverte automatique de l'URL du calendrier iCloud
- Création d'un fichier `.ics` avec :
  - Titre : "Entretien — [Entreprise]"
  - Date/heure extraite de l'email du recruteur
  - Description avec poste, entreprise, notes
  - **2 rappels (VALARM)** : 24h avant et 1h avant
- Si aucune date trouvée → événement placeholder 7 jours à l'avance

### Credentials
Variables Railway : `ICLOUD_EMAIL` + `ICLOUD_APP_PASSWORD`

---

## Alumni Hetic (LinkedIn + Hunter.io)

**Fichier :** `alumni_linkedin.py`

### Fonctionnement
1. **Découverte** via DuckDuckGo HTML (pas d'API payante) :
   - 6 requêtes : `site:linkedin.com/in "Hetic" "Data Analyst" Paris`, etc.
   - Parse les titres LinkedIn : "Prénom NOM - Poste chez Entreprise | LinkedIn"
2. **Email** via Hunter.io : `prenom.nom@entreprise.com`
3. **Email de networking** généré par Claude Haiku :
   - 160–200 mots
   - Mentionne Hetic + l'agent IA comme projet concret
   - Demande un retour d'expérience / conseil
4. Enregistrement en base (`alumni` table) avec statut de contact
5. Notification Telegram après chaque email envoyé

### Limites
- Max 5 alumni contactés par cycle
- Ne recontacte pas un alumni déjà contacté

---

## Notifications Telegram

**Fichier :** `notifier.py`, `candidater.py`, `main.py`

### Commandes disponibles

| Commande | Description |
|----------|-------------|
| `/offres` | Top 10 offres intéressantes avec boutons Intéressé / Ignorer / Email |
| `/stats` | Statistiques globales via Claude |
| `/cycle` | Lancer manuellement un cycle complet |
| `/candidatures` | 15 dernières candidatures avec statut et canal |
| `/relances` | Candidatures à relancer + bouton "Relancer maintenant" |
| `/entretiens` | Offres en statut entretien |
| `/alumni` | Alumni Hetic contactés et en attente |
| `/help` | Liste de toutes les commandes |
| `/reset` | Réinitialiser la conversation |
| Message libre | Conversation Claude avec contexte de recherche d'emploi |
| Photo/image | Analyse d'offre ou de CV par Claude Vision |
| PDF | Extraction texte + analyse (CV conseils ou offre match) |

### Notifications automatiques
- **Alerte immédiate** pour chaque offre ≥ 90% (juste après le scoring)
- **Rapport de cycle** : nouvelles offres, candidatures, relances, alumni, entretiens
- **Résumé quotidien à 20h** : candidatures du jour, offres intéressantes, sources actives
- **Bilan hebdomadaire chaque lundi à 09h** :
  - Offres trouvées + offres intéressantes cette semaine
  - Candidatures par canal (email, formulaire, Easy Apply)
  - Top 5 offres de la semaine
  - Entretiens obtenus
  - Alumni contactés
  - Totaux cumulés + taux de réponse

### Inline keyboards
- **Offres :** ✅ Intéressé | ❌ Ignorer | 📧 Email → génère et propose un brouillon
- **Email brouillon :** 📤 Envoyer maintenant | ❌ Annuler
- **Relances :** 📤 Relancer maintenant | ❌ Ignorer

---

## Dashboard web (Flask)

**Fichier :** `dashboard.py`

### Accès
Déployé sur Railway : `worker-production-691b.up.railway.app`

### Endpoints REST

| Route | Description |
|-------|-------------|
| `GET /` | Dashboard HTML (page unique) |
| `GET /api/stats` | Stats globales JSON |
| `GET /api/candidatures` | 50 dernières candidatures |
| `GET /api/offres` | Top 30 offres intéressantes |
| `GET /api/alumni` | Derniers alumni contactés |

### Fonctionnalités
- Thème sombre (`#0f1117` fond, `#1a1d2e` cartes)
- **Auto-refresh toutes les 30 secondes** (JS `setInterval`)
- Cartes statistiques : total offres, candidatures, entretiens, taux de réponse
- Tableau des candidatures avec statut coloré
- Barres de sources (WTTJ, LinkedIn, Indeed, HelloWork, APEC, France Travail, LBA)
- Liste des alumni contactés
- Top offres avec score
- **Fallback Turso** : si SQLite local vide après redéploiement, lit les données depuis Turso cloud

### Lancement
Démarré en daemon thread au lancement de `main.py` (non bloquant)

---

## Persistance cloud (Turso)

**Fichier :** `turso_sync.py`

### Problème résolu
Railway redéploie le container à chaque push → le fichier SQLite local est réinitialisé → l'agent oublie toutes les candidatures et risque de repostuler aux mêmes offres.

### Solution
- **Turso** = base SQLite distribuée dans le cloud (HTTP REST API)
- À chaque cycle : sync bidirectionnelle SQLite local ↔ Turso cloud

### Tables synchronisées
- `offres_postulees` : URL + hash des offres déjà postulées
- `candidatures_log` : toutes les candidatures avec statut
- `alumni_log` : alumni contactés
- `emails_log` : emails envoyés

### Fonctions clés
- `init_turso()` : crée les tables si inexistantes
- `restaurer_statuts_depuis_turso()` : au démarrage, marque en local les offres déjà postulées
- `sync_candidatures_vers_turso()` : en fin de cycle, pousse les nouvelles candidatures
- `deja_postule_turso(url)` : vérifie en temps réel si une URL a déjà été postulée

---

## Déploiement Railway

### Cycle de vie
1. Push GitHub → Railway redéploie automatiquement
2. Au démarrage : `main.py` lance le dashboard Flask + le bot Telegram
3. 1h après le démarrage : premier cycle agent
4. Ensuite : cycle toutes les 8h automatiquement
5. Résumé quotidien à 20h, bilan hebdo lundi 9h

### Commande de démarrage
```
python main.py
```

---

## Variables d'environnement

| Variable | Description | Obligatoire |
|----------|-------------|-------------|
| `TELEGRAM_TOKEN` | Token du bot Telegram | Oui |
| `TELEGRAM_CHAT_ID` | ID du chat Telegram d'Ali | Oui |
| `ANTHROPIC_API_KEY` | Clé API Claude (Anthropic) | Oui |
| `TURSO_URL` | URL de la base Turso cloud | Oui |
| `TURSO_TOKEN` | Token d'authentification Turso | Oui |
| `GMAIL_ADDRESS` | Adresse Gmail pour l'envoi | Oui |
| `GMAIL_REFRESH_TOKEN` | Token de refresh Gmail OAuth2 | Oui |
| `GMAIL_CLIENT_ID` | Client ID Google OAuth2 | Oui |
| `GMAIL_CLIENT_SECRET` | Client Secret Google OAuth2 | Oui |
| `HUNTER_API_KEY` | Clé API Hunter.io | Oui |
| `FRANCE_TRAVAIL_CLIENT_ID` | Client ID France Travail API | Recommandé |
| `FRANCE_TRAVAIL_CLIENT_SECRET` | Client Secret France Travail API | Recommandé |
| `LINKEDIN_EMAIL` | Email LinkedIn pour Easy Apply | Recommandé |
| `LINKEDIN_PASSWORD` | Mot de passe LinkedIn | Recommandé |
| `ICLOUD_EMAIL` | Email iCloud pour le calendrier | Recommandé |
| `ICLOUD_APP_PASSWORD` | Mot de passe d'app iCloud | Recommandé |

---

## Installation locale

```bash
# Cloner le dépôt
git clone https://github.com/Alibenaqa/alternance_agent.git
cd alternance_agent

# Créer l'environnement virtuel
python3 -m venv venv
source venv/bin/activate

# Installer les dépendances
pip install -r requirements.txt

# Installer Playwright (pour Easy Apply + WTTJ)
playwright install chromium

# Copier et remplir les variables d'environnement
cp .env.example .env
# Éditer .env avec tes clés

# Placer le CV
cp /chemin/vers/cv_ali.pdf ./cv_ali.pdf

# Lancer l'agent
python main.py
```

---

## Structure des fichiers

```
alternance_agent/
│
├── main.py                     # Point d'entrée : bot Telegram + cycles auto
├── memory.py                   # Base SQLite locale + normalisation URLs
├── scorer.py                   # Scoring offres via Claude Haiku
├── notifier.py                 # Notifications Telegram + alertes top
├── candidater.py               # Candidatures auto + résumé quotidien + stats hebdo
├── emailer.py                  # Envoi emails via Gmail API OAuth2
├── hunter.py                   # Recherche email recruteur via Hunter.io
├── reponses.py                 # Lecture réponses Gmail + relances auto
├── calendrier.py               # Intégration iCloud CalDAV (entretiens)
├── turso_sync.py               # Persistance cloud Turso (anti-doublon Railway)
├── dashboard.py                # Dashboard web Flask (auto-refresh)
├── alumni_linkedin.py          # Outreach alumni Hetic (DDG + Hunter.io + Claude)
├── linkedin_easy_apply.py      # Candidatures LinkedIn Easy Apply (Playwright)
│
├── scraper_wttj.py             # Scraper Welcome to the Jungle (API)
├── scraper_linkedin.py         # Scraper LinkedIn (endpoint public)
├── scraper_indeed.py           # Scraper Indeed (HTML)
├── scraper_hellowork.py        # Scraper HelloWork (HTML)
├── scraper_labonnealternance.py # Scraper La Bonne Alternance (API)
├── scraper_france_travail.py   # Scraper France Travail (OAuth2 API)
├── scraper_apec.py             # Scraper APEC (API interne, pagination)
│
├── profil_ali.json             # Profil complet : formation, compétences, projets
├── cv_ali.pdf                  # CV à joindre aux candidatures
├── requirements.txt            # Dépendances Python
└── README.md                   # Ce fichier
```

---

## LinkedIn Agent — Problèmes rencontrés & solutions

Historique complet des obstacles techniques rencontrés lors du développement de `linkedin_agent.py` et des solutions appliquées.

---

### 1. Code 2FA LinkedIn jamais reçu à temps

**Problème :** La boucle de polling Telegram bloquait la session Playwright. Le code arrivait 5–10 minutes après, bien après l'expiration de la fenêtre LinkedIn.

**Solution :**
- Remplacement du polling par un `threading.Event` avec timeout 600s
- Ajout d'une route Flask `/set_code/<code>` comme canal alternatif (plus fiable quand Telegram est lent)
- L'utilisateur peut envoyer `/linkedin_code XXXXXX` **ou** ouvrir le lien direct

---

### 2. Page "Something unexpected happened" (Welcome Back)

**Problème :** LinkedIn détectait le bot au moment de soumettre le mot de passe sur la page "Welcome Back" et bloquait avec cette erreur.

**Solution :**
- Ignorer la page Welcome Back entièrement
- Vider les cookies (`page.context.clear_cookies()`) et aller directement sur `/login`
- Taper l'email et le mot de passe caractère par caractère avec `page.type()` + délai aléatoire 50–130ms

---

### 3. Champ `#username` introuvable

**Problème :** Le sélecteur `#username` ne fonctionnait pas sur LinkedIn en français, qui utilise `session_key`.

**Solution :** Sélecteurs multiples avec fallback :
```python
"#username, input[name='session_key'], input[autocomplete='username'], input[type='email']"
```

---

### 4. CAPTCHA après plusieurs tentatives

**Problème :** L'IP du container Railway est blacklistée par LinkedIn après quelques connexions, affichant un CAPTCHA impossible à résoudre en headless.

**Solution :**
- Script `export_linkedin_cookies.py` : exporte les cookies du vrai Chrome/Brave de l'utilisateur vers Turso
- À chaque session, le bot charge ces cookies depuis Turso et les injecte dans le contexte Playwright
- La session est authentifiée via les cookies réels, LinkedIn ne voit pas une connexion suspecte

---

### 5. Vérification par notification push (pas de champ code)

**Problème :** LinkedIn envoyait une notification push dans l'app mobile au lieu d'un code email. Le bot attendait un code qui n'allait jamais arriver.

**Solution :**
- Détection de la page push ("Consultez votre appli LinkedIn")
- Envoi d'un message Telegram demandant à l'utilisateur de taper "Oui" dans l'app
- Boucle d'attente 3 minutes (36 × 5s) qui vérifie si la connexion est établie

---

### 6. Toutes les actions retournent 0

**Problème :** Après une connexion réussie, toutes les actions (connexions, likes, commentaires, DMs) ne faisaient rien. La session se terminait en 2 minutes avec tout à 0.

**Cause :** Les sélecteurs CSS (`div[class*='feed-shared-update']`, `li.mn-connection-card`, `button[aria-label*='Like']`) étaient complètement obsolètes — LinkedIn a refondu son DOM.

**Solution :** Réécriture de toutes les fonctions pour ne plus dépendre des classes CSS :
- Profils : `a[href*='/in/']` (stable depuis toujours)
- Feed : JS qui remonte depuis les liens de posts (`/feed/update/`, `/posts/`) vers les containers
- DMs : JS qui extrait les connexions depuis les liens `/in/` de la page connexions
- Likes : `button[aria-pressed="false"]` + filtre par mots-clés de réaction en JS

---

### 7. Noms de profils pollués (`\n • 2nd\nAI Engineer...`)

**Problème :** `inner_text()` sur un lien `/in/` retournait tout le texte de la carte (nom + badge + titre), rendant les noms inutilisables.

**Solution :** Extraction du premier span `aria-hidden="true"` (nom uniquement), avec fallback sur la première ligne non vide qui ne contient pas `•` ou `Connect`.

---

### 8. 0 profils trouvés pour les requêtes simples

**Problème :** Les requêtes courtes ("Software Engineer", "BI Analyst") retournaient 0 résultats parce que LinkedIn redirige vers une page d'accueil sans résultats.

**Solution :** Ajout du suffixe "France" à toutes les requêtes. Requêtes actuelles :
```python
["Data Analyst France", "Data Engineer France", "Data Scientist France",
 "Software Engineer France", "Machine Learning France", "Recruteur tech Paris", ...]
```

---

### 9. Session bloquée 4+ minutes (debug loops)

**Problème :** Des boucles Python itéraient `get_attribute()` sur 20 boutons un par un — chaque appel Playwright est une IPC synchrone. Sur Railway, avec la latence réseau, ça prenait 4 minutes pour un simple debug.

**Solution :** Supprimer toutes les boucles de debug Python. Remplacer par des appels `page.evaluate()` JS qui font tout le travail en un seul round-trip et retournent un tableau.

---

### 10. Page crashed (Out Of Memory Railway)

**Problème :** Le container Railway a une RAM limitée. LinkedIn charge des images, vidéos, polices et scripts lourds. Après 3–4 navigations, le navigateur crashait avec `Page.goto: Page crashed`.

**Solutions appliquées :**
- `page.route()` pour bloquer les ressources `image` et `media` avant téléchargement (−70% RAM)
- `wait_until="domcontentloaded"` au lieu de `load` — s'arrête avant les scripts lourds
- `page.goto("about:blank")` avant chaque profil pour vider le DOM et libérer la RAM
- Page fraîche (`ctx.new_page()`) entre chaque action de session (connexions, likes, DMs, etc.)
- Flag Chromium `--blink-settings=imagesEnabled=false` comme couche supplémentaire

---

### 11. Bouton "Se connecter" introuvable

**Problème :** Le sélecteur `button:has-text('Se connecter')` ne trouvait rien même sur des profils où le bouton était visible en screenshot.

**Cause :** Quand les CSS chargent partiellement (à cause des blocages RAM), LinkedIn rend le bouton Connect comme un `<a>` (lien) au lieu d'un `<button>`.

**Solution :** Sélecteurs étendus pour couvrir les deux cas :
```python
"button:has-text('Connect'), button:has-text('Se connecter'), "
"a:has-text('Connect'), a:has-text('Se connecter'), "
"button[aria-label*='Connect'], button[aria-label*='Inviter']"
```

---

### 12. Profil vide au chargement (React pas encore rendu)

**Problème :** Avec `domcontentloaded`, Playwright s'arrêtait avant que React ait rendu le contenu du profil. La page était grise, aucun bouton n'existait.

**Solution :** Attendre l'apparition de `<main>` après le chargement :
```python
page.wait_for_selector("main", timeout=8000)
```

---

### 13. DMs filtrés à 0 (poste vide = "autre")

**Problème :** L'extraction JS du poste sur la page connexions retournait souvent une chaîne vide. `_classifier_profil("")` retournait `"autre"`, et le filtre `if type_profil == "autre": continue` éliminait 100% des connexions.

**Solution :** Supprimer le filtre strict. Si le poste est vide ou inconnu, utiliser le template `data_tech` (networking générique) par défaut.

---

### 24. Connexion envoyée mais retourne False (modale ou envoi direct)

**Problème :** Après `connect_idx=14` (bouton trouvé, clic effectué), la fonction retournait False. LinkedIn a deux comportements : soit il ouvre une modale avec un bouton "Envoyer", soit il envoie directement sans modale. Le code cherchait `btn_envoyer.is_visible()` mais ne gérait pas l'envoi direct.

**Solution :**
1. Après le clic Connect, JS cherche un bouton "envoyer"/"send" dans la page
2. Si trouvé → modale ouverte → clic sur Envoyer
3. Sinon → vérifier si le bouton Connect a disparu de la page → si oui, connexion envoyée directement

---

### 21. Likes : Target crashed après le 3e like

**Problème :** Le JS évaluait les indices des boutons une seule fois au début. Après chaque like + pause (3-8s), le feed scrollait, de nouveaux boutons apparaissaient, les anciens indices devenaient invalides → `Target crashed` sur tous les boutons restants.

**Solution :** Re-évaluer l'index du prochain bouton de réaction en JS **après chaque like**, en cherchant le premier bouton `aria-pressed != "true"` avec un mot-clé de réaction. Plus d'indices stables = plus de crash.

---

### 22. Connexions : connect_idx = -1 sur tous les profils

**Problème :** Le JS cherchait exactement `"connect"` ou `"se connecter"` mais les boutons LinkedIn peuvent avoir des aria-labels comme `"Inviter Mohamed Ali à se connecter"` — le match exact échouait.

**Solution :** Ajouter un log complet (`connect_idx=X — 0:label | 1:label...`) dans le session log pour voir exactement ce que LinkedIn affiche sur les profils visités.

---

### 23. Feed : 0 posts (auteur requis mais absent)

**Problème :** Le scraper ignorait les posts sans lien `/in/` trouvé dans le container. Certains posts n'ont pas de lien auteur accessible dans le DOM partiel.

**Solution :** Rendre l'auteur optionnel — accepter le post même sans auteur, avec fallback `"LinkedIn"`.

---

### 20. Session bloquée sur commentaires (feed trop lent)

**Problème :** `_scraper_feed` accumulait : 8s `wait_for_selector` + 5 scrolls × 1.5-2.5s = jusqu'à 20s juste pour charger le feed. Avec 4 commentaires max et les appels Claude, la session pouvait rester bloquée 15+ minutes.

**Solution :**
- Réduire à 2 scrolls × 1-1.5s
- Supprimer le `wait_for_selector` (ajouter un simple `_pause(3,4)` à la place)
- Plafonner les valeurs aléatoires de session : connexions 2-5, commentaires 0-2, likes 1-4, DMs 0-2

---

### 17. Bouton Connect introuvable (sélecteur CSS vs JS)

**Problème :** `page.locator("button:has-text('Connect')")` retournait un locator vide même quand le bouton était visible dans le screenshot. Résidu de l'ancien `btn_connect.click()` après la réécriture.

**Solution :** Utiliser `page.evaluate()` JS pour parcourir tous les `button` et `a` et retourner l'index de celui dont le texte/aria-label correspond exactement à "connect" / "se connecter" / "inviter". Plus fiable que les sélecteurs Playwright qui dépendent du contexte.

---

### 18. DMs : 0 connexions trouvées (networkidle bloqué)

**Problème :** `page.wait_for_load_state("networkidle")` ne se résolvait jamais car `page.route()` intercepte les requêtes image/media, ce qui empêche LinkedIn d'atteindre l'état "networkidle" (réseau inactif).

**Solution :** Remplacer par `domcontentloaded` + `wait_for_selector("a[href*='/in/']", timeout=8000)` — attend que les liens de profils soient présents dans le DOM.

---

### 19. Feed : 0 posts (span[dir=ltr] pas encore rendu)

**Problème :** Le scraper cherchait les `span[dir="ltr"]` juste après `domcontentloaded`, avant que React ait rendu les posts.

**Solution :** Ajouter `wait_for_selector("span[dir='ltr']", timeout=8000)` avant de lancer le JS de scraping — attend que le premier texte de post soit présent.

---

### 16. Session bloquée 15+ minutes sur les connexions

**Problème :** Avec 6 connexions, la session mettait plus de 15 minutes. Chaque profil accumulait : `about:blank` (1s) + `goto profil` (25s max) + `wait main` (8s) + pause (2-3s) + appel Claude pour la note (3-10s) + pause après (4-10s) + pause entre queries (5-12s) = ~50-60s par profil × 6 queries × 3 profils = ~15 min.

**Solution :** Réduction de toutes les pauses :
- Entre profils : 4-10s → 2-4s
- Entre queries : 5-12s → 2-5s
- Entre actions de session : 5-15s → 2-5s
- Profils par query : 3 → 2
- Timeout `wait_for_selector("main")` : 8s → 5s
- Suppression du flush `about:blank` (économise 1-2s par profil)

Résultat : session 6 connexions ~3-4 minutes au lieu de 15.

---

### 15. Feed scrapé : 0 posts (liens /posts/ absents du DOM)

**Problème :** Le scraper cherchait les liens `a[href*="/posts/"]` et `a[href*="/feed/update/"]` comme point de départ. Ces liens n'existent pas dans le DOM quand les ressources sont bloquées (images/media interceptés par `page.route()`).

**Solution :** Inverser la logique — partir des **textes** (`span[dir="ltr"]` > 80 chars) qui eux sont toujours dans le DOM, puis remonter le DOM pour trouver l'auteur (lien `/in/`) et l'URL optionnelle du post. Résultat : le scraper fonctionne même sans CSS ni images.

---

### 14. Feed scrapé : 0 posts (mauvais argument JS)

**Problème :** `page.evaluate(f"(maxPosts) => {{ ... }}, {max_posts}")` — le `max_posts` était interpolé **dans la string** au lieu d'être passé comme second argument de `evaluate`. La fonction JS recevait `undefined` comme argument.

**Solution :**
```python
# Avant (cassé)
page.evaluate(f"(maxPosts) => {{ ... }}, {max_posts}")
# Après (correct)
page.evaluate("(maxPosts) => { ... }", max_posts)
```

---

### 25. Connexions : invitation jamais envoyée (modal de confirmation ignoré)

**Problème :** Après avoir cliqué "Invite [Name] to connect" sur la page de résultats de recherche, LinkedIn ouvre systématiquement un **modal de confirmation** avec un bouton "Send now" / "Envoyer maintenant". L'ancien code cliquait le bouton Connect mais ne gérait pas ce modal. Résultat : l'invitation restait en suspend, `envoyes` ne s'incrémentait jamais → 0 connexions.

**Solution :**
- Transformer la boucle JS-bulk (qui cliquait plusieurs boutons d'un coup) en boucle Python qui clique **un bouton à la fois**
- Après chaque clic Connect, pause 1s puis JS cherche un bouton "send now" / "envoyer maintenant" / "envoyer" / "suivant" dans le DOM et le clique
- Log Telegram du label du bouton modal pour diagnostiquer (`Modal géré : envoyer maintenant`)
- Ajout d'un log debug des boutons présents sur la page avant chaque tentative

```python
# Après chaque clic Connect :
_pause(1, 1.5)
modal_label = page.evaluate("""() => {
    const send_kw = ['send now', 'envoyer maintenant', 'envoyer', 'send', 'suivant', 'next'];
    for (const btn of [...document.querySelectorAll('button')]) {
        const label = (btn.getAttribute('aria-label') || btn.innerText || '').toLowerCase().trim();
        if (send_kw.some(kw => label.includes(kw))) { btn.click(); return label; }
    }
    return null;
}""")
```

---

### 26. Feed : 0 posts (domcontentloaded trop rapide pour React)

**Problème :** `_scraper_feed` naviguait vers `/feed/` avec `wait_until="domcontentloaded"` puis cherchait immédiatement les `span[dir="ltr"]`. React n'avait pas encore rendu les posts dans le DOM — le JS retournait un tableau vide même si des posts existaient.

**Solution :**
- Ajouter `page.wait_for_selector("div[data-id], article, .feed-shared-update-v2, div[data-urn]", timeout=8000)` après le `goto` pour attendre le rendu
- Augmenter les scrolls de 2 à 4 (charge plus de posts)
- Ajouter un log debug `Total spans[dir=ltr] dans le DOM : X` pour diagnostiquer si le DOM est vide ou bien peuplé

---

| Catégorie | Technologies |
|-----------|-------------|
| Langage | Python 3.14 |
| IA / LLM | Anthropic Claude Haiku 4.5 (scoring, emails, réponses) |
| Bot | python-telegram-bot 22.7 (job-queue) |
| Scraping HTML | BeautifulSoup4, requests |
| Automatisation navigateur | Playwright (Chromium headless) |
| Base de données locale | SQLite (via module `sqlite3`) |
| Base de données cloud | Turso (SQLite distribué, HTTP REST) |
| Email | Gmail API OAuth2 |
| Dashboard | Flask 3.1.0 |
| Déploiement | Railway.app |
| Calendrier | iCloud CalDAV (protocole HTTP) |

---

---

## Profil candidat

**Ali Benaqa** — [alibenaqa123@gmail.com](mailto:alibenaqa123@gmail.com) | +33 6 67 67 79 37 | Paris (75011)

**Formation :** Bachelor Data & Intelligence Artificielle — Hetic Montreuil
2e année actuellement · 3e année (Bac+3) dès septembre 2026 · Alternance recherchée à partir d'octobre 2026

**Expériences :**
- Data Analyst freelance — Techwin Services (mars–juin 2025) : pipelines ETL Python, traitement CSV/SQL/API, automatisation datasets
- Reporting Analyst (stage) — Mamda Assurance Maroc (avr–août 2024) : apps web PHP/MySQL, reporting automatisé Power BI, optimisation interfaces data
- Data Analyst — BNC Corporation Maroc (sept 2023–avr 2024) : KPI commerciaux, tableaux de bord Power BI, analyses EViews/Excel

**Compétences :** Python · SQL · Power BI · ETL · JavaScript · Node.js · React · PHP · MySQL · PostgreSQL · MongoDB · Git · Docker (bases) · Make · ChatGPT API · Claude API

**Projets :**
- **[Alternance Agent](https://github.com/Alibenaqa/alternance_agent)** — Agent IA autonome de recherche d'alternance (Python, Claude API, Playwright, Railway, Telegram, Flask) : scrape 8 plateformes, score les offres, postule automatiquement avec CV joint, relances auto, dashboard web
- **[AniData Lab](https://github.com/Alibenaqa/anidata_lab)** — Pipeline ETL end-to-end sur 17 562 titres anime + 57M ratings (Python, Pandas, Elasticsearch, Logstash, Grafana, Apache Airflow 2.x, Docker) : DAGs d'indexation quotidienne, détection d'anomalies, dashboards Grafana
- **[Dream Interpreter](https://github.com/Alibenaqa/dream_interpreter)** — App IA générative d'analyse de rêves (Python, Groq API/Llama-3.3-70b, Whisper, Stable Diffusion XL, Streamlit) : transcription audio, interprétation LLM, génération d'images, journal de rêves
- **[Data Refinement](https://github.com/Alibenaqa/Data_refinement)** — Pipeline de nettoyage et contrôle qualité de données (Python, Pandas, NumPy, Jupyter) : 3 étapes exploration/nettoyage/standardisation sur dataset café corrompu
- **[Jeu de dames](https://github.com/Alibenaqa/jeu_de_dame)** — Jeu de dames complet en Python/Pygame, architecture orientée objet, séparation logique de jeu / interface graphique

**Langues :** Français bilingue · Anglais B2/C1 · Espagnol A1/A2

**Liens :** [GitHub](https://github.com/Alibenaqa) · [LinkedIn](https://www.linkedin.com/in/mohamed-ali-benaqa-209630264/)

*Agent développé de A à Z par Ali Benaqa dans le cadre de sa recherche d'alternance.*
