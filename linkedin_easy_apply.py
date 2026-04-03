"""
linkedin_easy_apply.py — Postule via LinkedIn Easy Apply (Playwright)

Stratégie :
1. Connexion LinkedIn avec les identifiants d'Ali
2. Récupère les offres LinkedIn intéressantes (score >= 0.75) pas encore postulées
3. Pour chaque offre : clique sur "Candidature simplifiée" (Easy Apply)
4. Remplit le formulaire : email, téléphone, upload CV
5. Pour les questions supplémentaires → Claude génère une réponse
6. Soumet et notifie Telegram

Variables Railway à ajouter :
  LINKEDIN_EMAIL
  LINKEDIN_PASSWORD
"""

import os
import time
import random
import requests as req
from pathlib import Path

import anthropic

from memory import Memory

LINKEDIN_EMAIL    = os.environ.get("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD = os.environ.get("LINKEDIN_PASSWORD", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "8658482373:AAH3Oxk6of_JWCVXRBXn_L4X9cIaHHMcDrc")
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "7026975488")

CV_PATH        = Path(__file__).parent / "cv_ali.pdf"
SCORE_MIN      = 0.75
MAX_PAR_CYCLE  = 8   # max candidatures Easy Apply par cycle

# Infos profil Ali (pour remplir les formulaires)
PROFIL = {
    "email":     "mohamedalibenaqa@gmail.com",
    "telephone": "+33667677937",
    "prenom":    "Mohamed Ali",
    "nom":       "Benaqa",
    "ville":     "Paris",
}


def _telegram(texte: str):
    try:
        req.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": texte, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass


def _pause(mini=1.5, maxi=3.5):
    """Pause aléatoire pour simuler un comportement humain."""
    time.sleep(random.uniform(mini, maxi))


# ────────────────────────────────────────────────
# RÉPONSE AUX QUESTIONS CUSTOM VIA CLAUDE
# ────────────────────────────────────────────────

def _repondre_question(question: str, offre: dict) -> str:
    """Claude génère une réponse courte à une question du formulaire Easy Apply."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""Tu remplis un formulaire de candidature LinkedIn Easy Apply pour Ali Benaqa.

Poste : {offre.get('titre', '')}
Entreprise : {offre.get('entreprise', '')}

PROFIL ALI :
- 2e année Bachelor Data & IA, Hetic Montreuil (3e année dès sept. 2026)
- Expériences : Data Analyst freelance Techwin Services (ETL Python, pipelines), Reporting Analyst stage Mamda Assurance Maroc (Power BI, PHP/MySQL), Data Analyst BNC Corporation Maroc (KPI, EViews, tableaux de bord)
- Stack : Python, SQL, Power BI, ETL, JavaScript, Node.js, React, PHP, MySQL, PostgreSQL, MongoDB, Git, Make, Claude API
- Projets phares : Alternance Agent (Python/Claude API/Railway/Telegram), AniData Lab (ETL Airflow/ELK/Docker, 57M ratings), Dream Interpreter (LLM Groq/Whisper/Stable Diffusion), Data Refinement (Pandas/Jupyter), Jeu de dames (Python/Pygame/OOP)
- Langues : Français bilingue, Anglais B2/C1, Espagnol A1/A2
- Disponibilité : Octobre 2026 | Paris (75011)

Question du formulaire : "{question}"

Réponds en 1-2 phrases MAX, directement utilisable dans le champ. Pas de guillemets autour.
Si c'est une question sur les années d'expérience → répondre "2 ans"
Si c'est sur le niveau d'études → "Bac+2 actuellement, Bac+3 dès septembre 2026"
Si c'est sur la disponibilité → "Octobre 2026"
Si c'est sur le salaire → "Grille alternance légale"
"""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception:
        return "2 ans"


# ────────────────────────────────────────────────
# CONNEXION LINKEDIN
# ────────────────────────────────────────────────

def _login(page) -> bool:
    """Se connecte à LinkedIn. Retourne True si succès."""
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

        # Vérifie si connecté (présence du nav LinkedIn)
        if "feed" in page.url or "mynetwork" in page.url or "jobs" in page.url:
            print("   ✅ LinkedIn connecté")
            return True

        # Parfois redirige vers /checkpoint (vérification de sécurité)
        if "checkpoint" in page.url or "challenge" in page.url:
            print("   ⚠️  LinkedIn demande une vérification — connexion manuelle requise")
            return False

        # Vérifie si on est sur la page d'accueil
        if page.locator("nav").count() > 0:
            print("   ✅ LinkedIn connecté")
            return True

        print(f"   ⚠️  URL après login : {page.url}")
        return False

    except Exception as e:
        print(f"   ❌ Erreur login LinkedIn : {e}")
        return False


# ────────────────────────────────────────────────
# REMPLISSAGE DU FORMULAIRE EASY APPLY
# ────────────────────────────────────────────────

def _remplir_etape(page, offre: dict) -> bool:
    """
    Remplit une étape du formulaire Easy Apply.
    Retourne True si le formulaire est complet (bouton Submit visible).
    """
    _pause(1, 2)

    # ── Champs standard ──────────────────────────────────────

    # Email
    for sel in ["input[id*='email']", "input[name='email']", "input[type='email']"]:
        try:
            el = page.locator(sel).first
            if el.is_visible():
                el.fill(PROFIL["email"])
                _pause(0.3, 0.8)
        except Exception:
            pass

    # Téléphone
    for sel in ["input[id*='phone']", "input[id*='phoneNumber']", "input[name*='phone']"]:
        try:
            el = page.locator(sel).first
            if el.is_visible():
                el.fill(PROFIL["telephone"])
                _pause(0.3, 0.8)
        except Exception:
            pass

    # Prénom
    for sel in ["input[id*='firstName']", "input[name*='firstName']"]:
        try:
            el = page.locator(sel).first
            if el.is_visible():
                el.fill(PROFIL["prenom"])
                _pause(0.3, 0.8)
        except Exception:
            pass

    # Nom
    for sel in ["input[id*='lastName']", "input[name*='lastName']"]:
        try:
            el = page.locator(sel).first
            if el.is_visible():
                el.fill(PROFIL["nom"])
                _pause(0.3, 0.8)
        except Exception:
            pass

    # Ville / adresse
    for sel in ["input[id*='city']", "input[id*='location']"]:
        try:
            el = page.locator(sel).first
            if el.is_visible():
                el.fill(PROFIL["ville"])
                _pause(0.3, 0.8)
        except Exception:
            pass

    # Upload CV
    if CV_PATH.exists():
        for sel in ["input[type='file']", "input[name*='resume']", "input[name*='cv']"]:
            try:
                el = page.locator(sel).first
                if el.count() > 0:
                    el.set_input_files(str(CV_PATH))
                    _pause(1, 2)
                    break
            except Exception:
                pass

    # ── Questions supplémentaires ─────────────────────────────

    # Questions texte libres
    questions_texte = page.locator("label + input[type='text']:not([id*='name']):not([id*='phone']):not([id*='email']):not([id*='city'])")
    for i in range(questions_texte.count()):
        try:
            champ = questions_texte.nth(i)
            if not champ.is_visible():
                continue
            # Trouve le label associé
            label_el = page.locator(f"label[for='{champ.get_attribute('id')}']")
            question_texte = label_el.inner_text() if label_el.count() > 0 else "Question"
            reponse = _repondre_question(question_texte, offre)
            champ.fill(reponse)
            _pause(0.5, 1)
        except Exception:
            pass

    # Questions textarea
    for textarea in page.locator("textarea").all():
        try:
            if not textarea.is_visible() or textarea.input_value():
                continue
            label_id = textarea.get_attribute("id") or ""
            label_el = page.locator(f"label[for='{label_id}']")
            question_texte = label_el.inner_text() if label_el.count() > 0 else "Décris ta motivation"
            reponse = _repondre_question(question_texte, offre)
            textarea.fill(reponse)
            _pause(0.5, 1)
        except Exception:
            pass

    # Select (dropdowns)
    for select in page.locator("select").all():
        try:
            if not select.is_visible():
                continue
            options = select.locator("option").all()
            if len(options) > 1:
                select.select_option(index=1)  # prend la 1re option non-vide
                _pause(0.3, 0.7)
        except Exception:
            pass

    # Radio buttons (oui/non → prend "Oui" ou la 1re option)
    for radio_group in page.locator("fieldset").all():
        try:
            if not radio_group.is_visible():
                continue
            oui = radio_group.locator("input[type='radio'][value='Yes'], input[type='radio'][value='true'], input[type='radio'][value='Oui']").first
            if oui.count() > 0 and oui.is_visible():
                oui.check()
            else:
                premier = radio_group.locator("input[type='radio']").first
                if premier.count() > 0 and premier.is_visible():
                    premier.check()
            _pause(0.3, 0.7)
        except Exception:
            pass

    # ── Bouton d'action ──────────────────────────────────────

    # Bouton Submit (dernière étape)
    submit = page.locator("button[aria-label='Envoyer la candidature'], button[aria-label='Submit application']").first
    if submit.count() > 0 and submit.is_visible():
        return True  # prêt à soumettre

    return False  # pas encore à la dernière étape


def _easy_apply(page, offre: dict) -> bool:
    """
    Tente de postuler via Easy Apply sur une offre LinkedIn.
    Retourne True si succès.
    """
    try:
        page.goto(offre["url"], timeout=20000)
        page.wait_for_load_state("networkidle", timeout=15000)
        _pause(2, 4)

        # Cherche le bouton Easy Apply
        btn_easy = page.locator(
            "button.jobs-apply-button, "
            "button[aria-label*='Easy Apply'], "
            "button[aria-label*='Candidature simplifiée']"
        ).first

        if btn_easy.count() == 0 or not btn_easy.is_visible():
            print(f"   ⏭️  Pas de bouton Easy Apply")
            return False

        btn_easy.click()
        _pause(2, 3)

        # Boucle sur les étapes (Next → Next → Submit)
        max_etapes = 8
        for etape in range(max_etapes):
            pret_soumettre = _remplir_etape(page, offre)

            if pret_soumettre:
                # Soumet la candidature
                submit_btn = page.locator(
                    "button[aria-label='Envoyer la candidature'], "
                    "button[aria-label='Submit application']"
                ).first
                submit_btn.click()
                _pause(2, 3)

                # Confirmation
                confirmation = page.locator(
                    "h3:has-text('Candidature envoyée'), "
                    "h3:has-text('Application submitted'), "
                    "div[data-test-modal-id='apply-success-modal']"
                ).first
                if confirmation.count() > 0:
                    print(f"   ✅ Candidature Easy Apply soumise !")
                else:
                    print(f"   ✅ Formulaire soumis (confirmation non détectée)")

                # Ferme le modal si présent
                try:
                    page.locator("button[aria-label='Fermer'], button[aria-label='Dismiss']").first.click()
                except Exception:
                    pass

                return True

            else:
                # Clique sur "Suivant" / "Next"
                next_btn = page.locator(
                    "button[aria-label='Continuer'], "
                    "button[aria-label='Continue to next step'], "
                    "button:has-text('Suivant'), "
                    "button:has-text('Next')"
                ).first

                if next_btn.count() == 0 or not next_btn.is_visible():
                    print(f"   ⚠️  Aucun bouton Suivant/Submit trouvé à l'étape {etape + 1}")
                    break

                next_btn.click()
                _pause(1.5, 3)

        print(f"   ⚠️  Max étapes atteint sans soumission")
        return False

    except Exception as e:
        print(f"   ❌ Erreur Easy Apply : {e}")
        return False


# ────────────────────────────────────────────────
# CYCLE PRINCIPAL
# ────────────────────────────────────────────────

def run_linkedin_easy_apply() -> dict:
    """
    Se connecte à LinkedIn et postule en Easy Apply aux offres LinkedIn éligibles.
    Retourne les stats du cycle.
    """
    if not LINKEDIN_EMAIL or not LINKEDIN_PASSWORD:
        print("⚠️  LINKEDIN_EMAIL ou LINKEDIN_PASSWORD manquant — skip Easy Apply")
        return {"candidatures": 0, "echecs": 0}

    if not CV_PATH.exists():
        print("⚠️  cv_ali.pdf introuvable — skip Easy Apply")
        return {"candidatures": 0, "echecs": 0}

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("⚠️  Playwright non installé — skip Easy Apply")
        return {"candidatures": 0, "echecs": 0}

    from turso_sync import deja_postule_turso

    mem = Memory()

    # Offres LinkedIn éligibles (pas encore postulées, score >= 0.75)
    with mem._connect() as conn:
        offres = conn.execute("""
            SELECT * FROM offres
            WHERE source = 'linkedin'
              AND statut = 'intéressant'
              AND score_pertinence >= ?
            ORDER BY score_pertinence DESC
            LIMIT ?
        """, (SCORE_MIN, MAX_PAR_CYCLE * 2)).fetchall()

    # Filtre anti-doublon Turso
    offres_filtrees = []
    for o in offres:
        o = dict(o)
        if deja_postule_turso(o["url"]):
            print(f"   ⏭️  Déjà postulé (Turso) : {o['titre']}")
            mem.update_offre_statut(o["id"], "postulé", "Déjà postulé (Turso)")
        else:
            offres_filtrees.append(o)
        if len(offres_filtrees) >= MAX_PAR_CYCLE:
            break

    offres = offres_filtrees
    print(f"\n🔗 LinkedIn Easy Apply — {len(offres)} offre(s) éligible(s)")

    if not offres:
        return {"candidatures": 0, "echecs": 0}

    stats = {"candidatures": 0, "echecs": 0}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                  "--no-zygote", "--disable-setuid-sandbox", "--no-first-run"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()

        # Connexion
        if not _login(page):
            print("   ❌ Impossible de se connecter à LinkedIn")
            _telegram("⚠️ <b>LinkedIn Easy Apply</b> : connexion échouée — vérifie les identifiants Railway (LINKEDIN_EMAIL / LINKEDIN_PASSWORD)")
            browser.close()
            return stats

        # Candidatures
        for offre in offres:
            print(f"\n➡️  {offre['titre']} — {offre['entreprise']} ({int(offre['score_pertinence']*100)}%)")

            ok = _easy_apply(page, offre)

            if ok:
                mem.add_candidature({
                    "offre_id": offre["id"],
                    "canal":    "linkedin_easy_apply",
                    "email_dest": "",
                    "objet_email": f"Easy Apply — {offre['titre']}",
                    "corps_email": "",
                })
                mem.update_offre_statut(offre["id"], "postulé", "Via LinkedIn Easy Apply")
                stats["candidatures"] += 1

                _telegram(
                    f"✅ <b>Easy Apply envoyé !</b>\n\n"
                    f"🏢 <b>{offre['entreprise']}</b> — {offre['titre']}\n"
                    f"⭐ Score : {int(offre['score_pertinence']*100)}%\n"
                    f"🔗 {offre['url']}\n\n"
                    f"CV envoyé directement sur LinkedIn 📄"
                )
            else:
                stats["echecs"] += 1

            _pause(3, 6)  # pause entre candidatures pour éviter le ban

        browser.close()

    print(f"\n✅ Easy Apply terminé — {stats['candidatures']} envoyés, {stats['echecs']} échecs")
    return stats


if __name__ == "__main__":
    stats = run_linkedin_easy_apply()
    print(f"\n📊 {stats}")
