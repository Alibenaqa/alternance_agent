"""
linkedin_agent.py — Agent LinkedIn autonome

Sessions automatiques :
  - Lundi     : 3 sessions aléatoires entre 6h-17h
  - Mar-Ven   : 2 sessions aléatoires entre 9h-17h
  - Weekend   : aucune activité

Chaque session :
  - random.randint(0, 8) connexions avec profils data/IT/RH
  - random.randint(0, 4) commentaires (envoyés sur Telegram pour approbation)
  - Actions dans ordre aléatoire, pauses humaines

Variables Railway :
  LINKEDIN_EMAIL
  LINKEDIN_PASSWORD
"""

import os
import re
import random
import time
import json
import requests as req

import anthropic

from hunter import trouver_email_recruteur
from emailer import envoyer_email

MOTS_RH = ["rh", "hr", "recruteur", "recrutement", "recruitment", "talent", "people",
           "chro", "drh", "staffing", "talent acquisition", "hiring manager"]
MOTS_DATA_TECH = ["data analyst", "data scientist", "data engineer", "machine learning",
                  "ml engineer", "ai engineer", "devops", "mlops", "software engineer",
                  "développeur", "developer", "bi analyst", "business intelligence",
                  "analytics", "ingénieur données", "fullstack", "backend", "frontend"]

LINKEDIN_EMAIL    = os.environ.get("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD = os.environ.get("LINKEDIN_PASSWORD", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "")

MAX_CONNEXIONS_JOUR  = 15
MAX_COMMENTAIRES_JOUR = 6

# Profils cibles pour les connexions
RECHERCHES_CONNEXION = [
    "Data Analyst France",
    "Data Scientist Paris",
    "Data Engineer France",
    "Machine Learning Engineer France",
    "DevOps Engineer Paris",
    "AI Engineer France",
    "Recruteur IT Paris",
    "Talent Acquisition data tech",
    "Business Intelligence Analyst France",
    "MLOps Engineer France",
]

NOTE_MAX_CHARS = 300  # LinkedIn limite les notes de connexion

# ─────────────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────────────

def _telegram(texte: str, buttons: list = None):
    """Envoie un message Telegram, avec boutons inline optionnels."""
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": texte,
        "parse_mode": "HTML",
    }
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    try:
        req.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json=payload,
            timeout=10,
        )
    except Exception:
        pass


def _telegram_edit(chat_id, message_id: int, texte: str):
    try:
        req.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText",
            json={"chat_id": chat_id, "message_id": message_id, "text": texte, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────
# CLAUDE
# ─────────────────────────────────────────────────────

def _claude(prompt: str, max_tokens: int = 300) -> str:
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        print(f"   ❌ Claude : {e}")
        return ""


def _classifier_profil(poste: str) -> str:
    """Retourne 'rh', 'data_tech', ou 'autre'."""
    p = poste.lower()
    if any(m in p for m in MOTS_RH):
        return "rh"
    if any(m in p for m in MOTS_DATA_TECH):
        return "data_tech"
    return "autre"


def _generer_email_profil(profil: dict, type_profil: str) -> dict:
    """Génère un email adapté selon le type de profil (rh ou data_tech)."""
    prenom    = profil.get("prenom", "")
    poste     = profil.get("poste", "")
    entreprise = profil.get("entreprise", "")

    if type_profil == "rh":
        prompt = f"""Rédige un email de candidature d'Ali Benaqa à destination d'un RH/recruteur trouvé sur LinkedIn.

DESTINATAIRE :
- Prénom : {prenom}
- Poste : {poste}
- Entreprise : {entreprise}

PROFIL ALI :
- 2e année Bachelor Data & IA, Hetic (3e année dès sept. 2026)
- Cherche alternance oct 2026, 12-36 mois, Paris/IDF ou remote
- Expériences : Data Analyst freelance Techwin (ETL Python), Reporting Analyst Mamda Assurance (Power BI/PHP), Data Analyst BNC Corporation (KPI/EViews)
- Projets : Alternance Agent (Python/Claude API/Railway), AniData Lab (ETL 57M ratings), Dream Interpreter (LLM+Whisper)
- Stack : Python, SQL, Power BI, ETL, JavaScript, Node.js, React, Docker, Git

RÈGLES :
- Commence par "Bonjour {prenom},"
- 3 paragraphes, 130-160 mots MAX
- Pas de "je me permets", "passionné", "dynamique", "opportunité"
- Mentionne qu'il a trouvé leur profil sur LinkedIn
- Demande clairement si {entreprise} recrute des alternants data/IA pour oct 2026
- Ton direct, professionnel mais humain
- Signature : Ali Benaqa | Hetic Bachelor Data & IA | +33 6 67 67 79 37
- Format : OBJET: [sujet]\\n---\\n[corps]"""

    else:  # data_tech
        prompt = f"""Rédige un email de networking d'Ali Benaqa à destination d'un professionnel data/tech trouvé sur LinkedIn.

DESTINATAIRE :
- Prénom : {prenom}
- Poste : {poste}
- Entreprise : {entreprise}

PROFIL ALI :
- 2e année Bachelor Data & IA, Hetic (3e année dès sept. 2026)
- Cherche alternance oct 2026 en data/IA
- Construit des projets concrets : agent IA autonome (Python/Claude API), pipeline ETL 57M données, app LLM+Whisper
- Stack : Python, SQL, Power BI, ETL, JavaScript, Docker

RÈGLES :
- Commence par "Bonjour {prenom},"
- 2-3 paragraphes, 120-150 mots MAX
- Ton chaleureux et curieux, pas corporate
- Mentionne qu'il a vu leur profil LinkedIn et trouvé leur parcours intéressant
- Demande des conseils/retours d'expérience sur leur domaine
- Mentionne brièvement un de ses projets concrets pour montrer son niveau
- PAS de demande de stage/alternance explicite (c'est du networking pur)
- Signature : Ali Benaqa | Hetic Bachelor Data & IA | +33 6 67 67 79 37
- Format : OBJET: [sujet]\\n---\\n[corps]"""

    texte = _claude(prompt, max_tokens=400)
    if not texte:
        return {}

    objet = f"Networking LinkedIn — Ali Benaqa"
    corps = texte
    if "OBJET:" in texte and "---" in texte:
        parties = texte.split("---", 1)
        objet = parties[0].replace("OBJET:", "").strip()
        corps = parties[1].strip()

    return {"objet": objet, "corps": corps}


def _tenter_email_profil(profil: dict, type_profil: str) -> bool:
    """Cherche l'email du profil via Hunter et envoie un email adapté."""
    entreprise = profil.get("entreprise", "")
    if not entreprise:
        return False

    print(f"   📧 Recherche email pour {profil['nom']} ({entreprise})...")
    contact = trouver_email_recruteur(entreprise)
    if not contact:
        print(f"   ❌ Aucun email trouvé pour {entreprise}")
        return False

    # Construit l'email personnalisé avec prénom.nom@domaine si possible
    import unicodedata
    def _norm(s):
        return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")

    domaine = contact.get("domaine", "")
    prenom_n = _norm(profil.get("prenom", ""))
    nom_parts = profil.get("nom", "").split()
    nom_n = _norm(nom_parts[-1]) if nom_parts else ""
    if prenom_n and nom_n and domaine:
        email_dest = f"{prenom_n}.{nom_n}@{domaine}"
    else:
        email_dest = contact.get("email", "")

    if not email_dest:
        return False

    email_data = _generer_email_profil(profil, type_profil)
    if not email_data:
        return False

    ok = envoyer_email(
        destinataire=email_dest,
        sujet=email_data["objet"],
        corps=email_data["corps"],
    )

    if ok:
        icon = "📧" if type_profil == "rh" else "🤝"
        print(f"   ✅ Email {type_profil} envoyé à {email_dest}")
        _telegram(
            f"{icon} <b>Email LinkedIn envoyé</b>\n"
            f"👤 {profil['nom']} — {profil['poste']} @ {entreprise}\n"
            f"📬 {email_dest}\n"
            f"📋 {email_data['objet']}"
        )

    return ok


def _generer_note_connexion(prenom: str, poste: str, entreprise: str) -> str:
    prompt = f"""Rédige une note de connexion LinkedIn de la part d'Ali Benaqa.

PROFIL ALI :
- Étudiant Bachelor Data & IA à Hetic (2e année, 3e année dès sept. 2026)
- Cherche alternance oct 2026 en data/IA
- 3 expériences : Data Analyst freelance (ETL Python), Reporting Analyst (Power BI), Data Analyst (KPI)
- Projets : agent IA alternance, AniData Lab (57M ratings), Dream Interpreter (LLM+Whisper)

DESTINATAIRE :
- Prénom : {prenom}
- Poste : {poste}
- Entreprise : {entreprise}

RÈGLES :
- Max 280 caractères (LinkedIn limite les notes)
- Ton direct et authentique, pas de "j'espère que vous allez bien"
- Mentionne un point commun ou un intérêt lié à leur poste
- Ne pas mentionner "alternance" directement dans la note de connexion (trop commercial)
- Juste élargir le réseau pro de façon naturelle
- Pas de signature (LinkedIn l'ajoute automatiquement)

Réponds uniquement avec le texte de la note, rien d'autre."""

    note = _claude(prompt, max_tokens=100)
    return note[:NOTE_MAX_CHARS] if note else f"Bonjour {prenom}, votre parcours en {poste} m'intéresse. Je développe des projets data/IA à Hetic et cherche à élargir mon réseau. Ali"


def _generer_commentaire(post_auteur: str, post_contenu: str, post_contexte: str) -> str:
    prompt = f"""Rédige un commentaire LinkedIn authentique de la part d'Ali Benaqa.

PROFIL ALI :
- Étudiant Bachelor Data & IA à Hetic, passionné par la data et l'IA
- Développe des projets concrets : agent IA autonome, pipeline ETL 57M données, app LLM
- Curieux, direct, pas de langue de bois

POST À COMMENTER :
Auteur : {post_auteur}
Contexte : {post_contexte}
Contenu : {post_contenu[:500]}

RÈGLES :
- 1-3 phrases max, naturel et sincère
- Ajoute de la valeur (pas juste "super post !")
- Peut partager une expérience personnelle liée au sujet
- Peut poser une question pertinente
- Ton jeune professionnel curieux, pas corporate
- Pas de hashtags, pas d'emojis excessifs (1 max)

Réponds uniquement avec le texte du commentaire."""

    return _claude(prompt, max_tokens=150)


def _evaluer_post(post_contenu: str) -> bool:
    """Claude décide si le post mérite un commentaire."""
    prompt = f"""Tu es Ali Benaqa, étudiant en Data & IA à Hetic.

Ce post LinkedIn vaut-il la peine d'être commenté ? Réponds uniquement "OUI" ou "NON".

Critères OUI : data, IA, machine learning, Python, carrière tech, recrutement IT, projets data, startups tech, conseils pros dans la tech
Critères NON : politique, sport, cuisine, développement personnel générique, pubs, témoignages sans rapport avec la tech

POST : {post_contenu[:400]}"""

    reponse = _claude(prompt, max_tokens=10)
    return "OUI" in reponse.upper()


# ─────────────────────────────────────────────────────
# UTILITAIRES PLAYWRIGHT
# ─────────────────────────────────────────────────────

def _pause(mini=1.5, maxi=4.0):
    time.sleep(random.uniform(mini, maxi))


def _pause_humaine():
    """Pause plus longue pour simuler la lecture."""
    time.sleep(random.uniform(3, 8))


def _launch_browser(playwright):
    browser = playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--no-zygote"],
    )
    ctx = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 800},
    )
    return browser, ctx


def _login(page) -> bool:
    try:
        page.goto("https://www.linkedin.com/login", timeout=20000)
        _pause(2, 4)
        page.fill("#username", LINKEDIN_EMAIL)
        _pause(0.5, 1.5)
        page.fill("#password", LINKEDIN_PASSWORD)
        _pause(0.5, 1.5)
        page.click("button[type='submit']")
        page.wait_for_load_state("networkidle", timeout=15000)
        _pause(2, 4)

        if any(x in page.url for x in ["feed", "mynetwork", "jobs"]):
            return True
        if "checkpoint" in page.url or "challenge" in page.url:
            print("   ⚠️  LinkedIn demande une vérification de sécurité")
            _telegram("⚠️ <b>LinkedIn</b> : vérification de sécurité requise — connexion impossible automatiquement")
            return False
        if page.locator("nav").count() > 0:
            return True

        print(f"   ⚠️  URL après login : {page.url}")
        return False
    except Exception as e:
        print(f"   ❌ Erreur login : {e}")
        return False


# ─────────────────────────────────────────────────────
# CONNEXIONS AUTOMATIQUES
# ─────────────────────────────────────────────────────

def _envoyer_connexion(page, profil_url: str, note: str) -> bool:
    """Ouvre un profil LinkedIn et envoie une demande de connexion avec note."""
    try:
        page.goto(profil_url, timeout=20000)
        _pause_humaine()

        # Cherche le bouton "Se connecter" / "Connect"
        btn_connect = page.locator(
            "button:has-text('Se connecter'), button:has-text('Connect'), "
            "button[aria-label*='Connect'], button[aria-label*='Se connecter']"
        ).first

        if not btn_connect.is_visible():
            # Parfois caché dans "Plus" / "More"
            btn_plus = page.locator("button:has-text('Plus'), button:has-text('More')").first
            if btn_plus.is_visible():
                btn_plus.click()
                _pause(1, 2)
                btn_connect = page.locator(
                    "div[role='menuitem']:has-text('Se connecter'), "
                    "div[role='menuitem']:has-text('Connect')"
                ).first

        if not btn_connect.is_visible():
            print(f"   ⏭️  Bouton connexion introuvable")
            return False

        btn_connect.click()
        _pause(1.5, 3)

        # Ajouter une note personnalisée
        btn_note = page.locator(
            "button:has-text('Ajouter une note'), button:has-text('Add a note')"
        ).first
        if btn_note.is_visible():
            btn_note.click()
            _pause(0.8, 1.5)
            textarea = page.locator("textarea[name='message'], textarea[id*='custom-message']").first
            if textarea.is_visible():
                textarea.fill(note)
                _pause(0.5, 1)

        # Envoyer
        btn_envoyer = page.locator(
            "button:has-text('Envoyer'), button:has-text('Send'), "
            "button[aria-label*='Envoyer'], button[aria-label*='Send invitation']"
        ).first
        if btn_envoyer.is_visible():
            btn_envoyer.click()
            _pause(1, 2)
            return True

        return False

    except Exception as e:
        print(f"   ❌ Erreur connexion : {e}")
        return False


def _chercher_profils(page, query: str, max_profils: int = 5) -> list[dict]:
    """Recherche des profils LinkedIn et retourne les résultats."""
    profils = []
    try:
        url = f"https://www.linkedin.com/search/results/people/?keywords={query.replace(' ', '%20')}&network=%5B%22S%22%2C%22O%22%5D"
        page.goto(url, timeout=20000)
        _pause_humaine()

        cards = page.locator("li.reusable-search__result-container").all()
        random.shuffle(cards)  # ordre aléatoire

        for card in cards[:max_profils * 2]:
            try:
                nom_el = card.locator("span.entity-result__title-text a span[aria-hidden='true']").first
                poste_el = card.locator("div.entity-result__primary-subtitle").first
                entreprise_el = card.locator("div.entity-result__secondary-subtitle").first
                lien_el = card.locator("a.app-aware-link").first

                nom = nom_el.inner_text().strip() if nom_el.count() else ""
                poste = poste_el.inner_text().strip() if poste_el.count() else ""
                entreprise = entreprise_el.inner_text().strip() if entreprise_el.count() else ""
                lien = lien_el.get_attribute("href") if lien_el.count() else ""

                if not nom or not lien:
                    continue

                # Filtre : déjà connecté ?
                if card.locator("span:has-text('1er'), span:has-text('1st')").count() > 0:
                    continue

                profils.append({
                    "nom": nom,
                    "prenom": nom.split()[0] if nom else "",
                    "poste": poste,
                    "entreprise": entreprise,
                    "url": lien.split("?")[0],
                })

                if len(profils) >= max_profils:
                    break
            except Exception:
                continue

    except Exception as e:
        print(f"   ❌ Recherche profils : {e}")

    return profils


def run_connexions(page, nb_connexions: int) -> int:
    """Lance nb_connexions demandes de connexion. Retourne le nombre réussi."""
    if nb_connexions == 0:
        return 0

    print(f"\n🔗 Connexions LinkedIn — {nb_connexions} cibles")
    envoyes = 0
    queries = random.sample(RECHERCHES_CONNEXION, min(nb_connexions, len(RECHERCHES_CONNEXION)))

    for query in queries:
        if envoyes >= nb_connexions:
            break

        print(f"   🔍 Recherche : '{query}'")
        profils = _chercher_profils(page, query, max_profils=3)

        for profil in profils:
            if envoyes >= nb_connexions:
                break

            print(f"   ➡️  {profil['nom']} — {profil['poste']} @ {profil['entreprise']}")

            # Classifie le profil pour adapter l'approche
            type_profil = _classifier_profil(profil["poste"])

            note = _generer_note_connexion(profil["prenom"], profil["poste"], profil["entreprise"])
            ok = _envoyer_connexion(page, profil["url"], note)

            if ok:
                envoyes += 1
                print(f"   ✅ Connexion envoyée ({envoyes}/{nb_connexions})")
                _telegram(
                    f"🔗 <b>Connexion envoyée</b>\n"
                    f"👤 {profil['nom']}\n"
                    f"💼 {profil['poste']} @ {profil['entreprise']}\n"
                    f"📝 Note : {note[:100]}..."
                )

                # Tente aussi un email si profil RH ou data/tech
                if type_profil in ("rh", "data_tech") and profil.get("entreprise"):
                    _pause(2, 4)
                    _tenter_email_profil(profil, type_profil)
            else:
                print(f"   ⏭️  Échec")

            _pause(4, 10)  # pause longue entre connexions

        _pause(5, 12)

    return envoyes


# ─────────────────────────────────────────────────────
# COMMENTAIRES (avec approbation Telegram)
# ─────────────────────────────────────────────────────

def _scraper_feed(page, max_posts: int = 10) -> list[dict]:
    """Scrape les posts du feed LinkedIn."""
    posts = []
    try:
        page.goto("https://www.linkedin.com/feed/", timeout=20000)
        _pause_humaine()

        # Scroll pour charger plus de posts
        for _ in range(3):
            page.evaluate("window.scrollBy(0, 800)")
            _pause(1.5, 3)

        articles = page.locator("div.feed-shared-update-v2").all()
        for article in articles[:max_posts]:
            try:
                # Auteur
                auteur_el = article.locator("span.feed-shared-actor__name").first
                auteur = auteur_el.inner_text().strip() if auteur_el.count() else "Inconnu"

                # Poste auteur
                titre_el = article.locator("span.feed-shared-actor__description").first
                titre_auteur = titre_el.inner_text().strip() if titre_el.count() else ""

                # Contenu du post
                contenu_el = article.locator("div.feed-shared-text").first
                contenu = contenu_el.inner_text().strip() if contenu_el.count() else ""

                if not contenu or len(contenu) < 50:
                    continue

                # URL du post
                lien_el = article.locator("a.app-aware-link[href*='/posts/']").first
                url_post = lien_el.get_attribute("href") if lien_el.count() else ""

                posts.append({
                    "auteur": auteur,
                    "titre_auteur": titre_auteur,
                    "contenu": contenu,
                    "url": url_post,
                })
            except Exception:
                continue

    except Exception as e:
        print(f"   ❌ Scraping feed : {e}")

    return posts


# Stockage temporaire des commentaires en attente d'approbation
_commentaires_pending: dict[str, dict] = {}


def run_commentaires(page, nb_commentaires: int, app) -> int:
    """Scrape le feed, génère des commentaires et les envoie sur Telegram pour approbation."""
    if nb_commentaires == 0:
        return 0

    print(f"\n💬 Commentaires LinkedIn — {nb_commentaires} cibles")
    posts = _scraper_feed(page, max_posts=15)
    random.shuffle(posts)

    envoyes = 0
    for post in posts:
        if envoyes >= nb_commentaires:
            break

        if not _evaluer_post(post["contenu"]):
            continue

        commentaire = _generer_commentaire(post["auteur"], post["contenu"], post["titre_auteur"])
        if not commentaire:
            continue

        # Clé unique pour ce commentaire en attente
        cle = f"comment_{int(time.time())}_{envoyes}"
        _commentaires_pending[cle] = {
            "commentaire": commentaire,
            "post_url": post.get("url", ""),
            "auteur": post["auteur"],
            "page_context": None,  # on re-naviguera au moment de poster
        }

        apercu = (
            f"💬 <b>Commentaire à approuver</b>\n\n"
            f"👤 Post de : <b>{post['auteur']}</b>\n"
            f"📝 Post : {post['contenu'][:200]}...\n\n"
            f"✍️ <b>Commentaire proposé :</b>\n{commentaire}"
        )

        buttons = [[
            {"text": "✅ Poster", "callback_data": f"linkedin_comment_ok:{cle}"},
            {"text": "❌ Skip",   "callback_data": f"linkedin_comment_skip:{cle}"},
        ]]

        _telegram(apercu, buttons)
        envoyes += 1
        _pause(2, 4)

    print(f"   ✅ {envoyes} commentaires envoyés sur Telegram pour approbation")
    return envoyes


async def poster_commentaire_approuve(cle: str, page) -> bool:
    """Poste le commentaire après approbation Telegram."""
    pending = _commentaires_pending.pop(cle, None)
    if not pending or not pending.get("post_url"):
        return False

    try:
        page.goto(pending["post_url"], timeout=20000)
        _pause_humaine()

        btn_comment = page.locator(
            "button[aria-label*='Comment'], button:has-text('Commenter')"
        ).first
        if btn_comment.is_visible():
            btn_comment.click()
            _pause(1, 2)

        textarea = page.locator("div.ql-editor[contenteditable='true']").first
        if textarea.is_visible():
            textarea.click()
            textarea.type(pending["commentaire"], delay=random.randint(30, 80))
            _pause(1, 2)

            btn_post = page.locator(
                "button.comments-comment-box__submit-button, "
                "button[aria-label*='Publier'], button:has-text('Publier')"
            ).first
            if btn_post.is_visible():
                btn_post.click()
                _pause(2, 3)
                return True
    except Exception as e:
        print(f"   ❌ Poster commentaire : {e}")

    return False


# ─────────────────────────────────────────────────────
# POSTS LINKEDIN (depuis Telegram /linkedin_post)
# ─────────────────────────────────────────────────────

_posts_pending: dict[str, str] = {}


def generer_post_linkedin(sujet: str) -> str:
    """Claude génère un post LinkedIn à partir d'une description."""
    prompt = f"""Rédige un post LinkedIn authentique de la part d'Ali Benaqa.

PROFIL ALI :
- Étudiant Bachelor Data & IA à Hetic (2e année, 3e année dès sept. 2026)
- Passionné par la data, l'IA et les projets concrets
- GitHub : https://github.com/Alibenaqa

SUJET DU POST : {sujet}

RÈGLES :
- Ton authentique, premier degré — pas de "ravi de partager", "fier de vous annoncer"
- 150-250 mots max
- Structure : accroche forte (1 ligne) → développement → appel à l'action ou question
- 2-3 hashtags pertinents max à la fin
- Peut inclure des chiffres/résultats concrets si pertinent
- Parle à la première personne

Réponds uniquement avec le texte du post, sans commentaires."""

    return _claude(prompt, max_tokens=400)


def publier_post(page, texte: str) -> bool:
    """Publie un post sur LinkedIn."""
    try:
        page.goto("https://www.linkedin.com/feed/", timeout=20000)
        _pause_humaine()

        # Clique sur "Démarrer un post"
        btn_start = page.locator(
            "button.share-box-feed-entry__trigger, "
            "span:has-text('Démarrer un post'), span:has-text('Start a post')"
        ).first
        if not btn_start.is_visible():
            return False
        btn_start.click()
        _pause(1.5, 3)

        # Rédige le post
        editor = page.locator("div.ql-editor[contenteditable='true']").first
        if not editor.is_visible():
            return False

        editor.click()
        editor.type(texte, delay=random.randint(20, 60))
        _pause(2, 4)

        # Publie
        btn_publier = page.locator(
            "button.share-actions__primary-action, "
            "button[aria-label='Publier'], button:has-text('Publier')"
        ).first
        if btn_publier.is_visible():
            btn_publier.click()
            _pause(3, 5)
            return True

        return False
    except Exception as e:
        print(f"   ❌ Publier post : {e}")
        return False


# ─────────────────────────────────────────────────────
# SESSION PRINCIPALE
# ─────────────────────────────────────────────────────

def run_linkedin_session(app=None) -> dict:
    """
    Lance une session LinkedIn autonome.
    Mix aléatoire de connexions + commentaires.
    """
    if not LINKEDIN_EMAIL or not LINKEDIN_PASSWORD:
        print("⚠️  LINKEDIN_EMAIL/PASSWORD manquants — skip session LinkedIn")
        return {"connexions": 0, "commentaires": 0}

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("⚠️  Playwright non installé")
        return {"connexions": 0, "commentaires": 0}

    # Mix aléatoire du jour
    nb_connexions   = random.randint(0, 8)
    nb_commentaires = random.randint(0, 4)

    print(f"\n🌐 Session LinkedIn — {nb_connexions} connexions, {nb_commentaires} commentaires")
    stats = {"connexions": 0, "commentaires": 0}

    # Ordre aléatoire des actions
    actions = (["connexions"] * nb_connexions) + (["commentaires"] * nb_commentaires)
    random.shuffle(actions)

    # Regroupe pour éviter de re-login entre chaque action
    nb_conn_final = actions.count("connexions")
    nb_comm_final = actions.count("commentaires")

    with sync_playwright() as p:
        browser, ctx = _launch_browser(p)
        page = ctx.new_page()

        if not _login(page):
            print("   ❌ Login LinkedIn échoué")
            _telegram("⚠️ <b>LinkedIn</b> : connexion échouée — vérifie les identifiants Railway")
            browser.close()
            return stats

        print("   ✅ LinkedIn connecté")

        # Connexions
        if nb_conn_final > 0:
            stats["connexions"] = run_connexions(page, nb_conn_final)
            _pause(5, 15)

        # Commentaires
        if nb_comm_final > 0:
            stats["commentaires"] = run_commentaires(page, nb_comm_final, app)

        browser.close()

    msg = (
        f"🌐 <b>Session LinkedIn terminée</b>\n"
        f"🔗 Connexions envoyées : {stats['connexions']}\n"
        f"💬 Commentaires proposés : {stats['commentaires']}"
    )
    _telegram(msg)
    print(f"\n✅ Session LinkedIn — {stats['connexions']} connexions, {stats['commentaires']} commentaires proposés")
    return stats


def get_commentaires_pending() -> dict:
    return _commentaires_pending


def get_posts_pending() -> dict:
    return _posts_pending
