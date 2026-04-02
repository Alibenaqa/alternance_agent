"""
candidater.py — Candidature automatique aux offres d'alternance
Logique : Hunter.io (email) → sinon formulaire WTTJ (Playwright)
Résumé quotidien envoyé à 20h sur Telegram.
"""

import os
import json
import requests as req
from datetime import datetime
from pathlib import Path

import anthropic

from memory import Memory
from hunter import trouver_email_recruteur
from emailer import envoyer_email


def _telegram(texte: str):
    req.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": texte, "parse_mode": "HTML"},
        timeout=10,
    )

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "8658482373:AAH3Oxk6of_JWCVXRBXn_L4X9cIaHHMcDrc")
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "7026975488")
BREVO_API_KEY     = os.environ.get("BREVO_API_KEY", "")
PROFIL_PATH       = Path(__file__).parent / "profil_ali.json"

SCORE_MIN_AUTO    = 0.75   # Score minimum pour candidature automatique
MAX_CANDIDATURES  = 10     # Max candidatures par cycle (évite le spam)


# ────────────────────────────────────────────────
# GÉNÉRATION EMAIL CLAUDE
# ────────────────────────────────────────────────

def generer_email_candidature(offre: dict) -> dict:
    """Génère un email de candidature personnalisé via Claude."""
    with open(PROFIL_PATH, "r", encoding="utf-8") as f:
        profil = json.load(f)

    r = profil["recherche_alternance"]
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""Rédige un email de candidature percutant et personnalisé pour Ali Benaqa.

PROFIL COMPLET D'ALI :
- Formation : Bachelor Data & IA — Hetic, Grande École de la Tech (Montreuil)
- Niveau actuel : Bac+2, sera en Bac+3 à partir d'octobre 2026
- Disponibilité : {r['disponibilite']} | Durée : {r['duree_contrat']} | Rythme : 3j entreprise / 2j école

EXPÉRIENCES :
  1. Data Analyst freelance — Techwin Services (mars-juin 2025)
     → Pipelines ETL Python, traitement données hétérogènes (CSV, SQL, API), pipelines automatisés
  2. Reporting Analyst (stage) — Mamda Assurance Maroc (avr-août 2024)
     → Apps web PHP/MySQL, reporting automatisé Power BI, optimisation interfaces data
  3. Data Analyst — BNC Corporation Maroc (sept 2023-avr 2024)
     → KPI commerciaux, tableaux de bord Power BI hebdo/mensuels, analyses EViews/Excel

PROJETS :
  - Agent IA autonome de recherche d'alternance (Python, Claude API, Playwright, Telegram, SQLite)
  - Bot Discord IA interactif (Node.js, ChatGPT API)
  - Site cinéma Espace des Arts, page live Betclic (UI/UX, HTML/CSS/JS)
  - Application de vote avec analyse données (Python, SQL)

COMPÉTENCES :
  - Data : Python, SQL, Power BI, ETL, EViews, pipelines de données, KPI
  - IA/ML : Claude API, ChatGPT API, intégration LLM, Make/Zapier, automatisation
  - Dev : JavaScript, Node.js, React, PHP, HTML/CSS, Express.js
  - Bases de données : MySQL, PostgreSQL, MongoDB
  - Outils : Git/GitHub, Docker (bases), Postman, Jira, GitHub Actions
  - Langues : français bilingue, anglais B2/C1

LIENS :
  - GitHub : https://github.com/Alibenaqa
  - LinkedIn : https://www.linkedin.com/in/mohamed-ali-benaqa-209630264/

OFFRE CIBLÉE :
- Poste : {offre['titre']}
- Entreprise : {offre['entreprise']}
- Localisation : {offre['localisation']}
- Description : {(offre.get('description') or 'Non précisée')[:800]}

INSTRUCTIONS :
- Style : professionnel mais humain, direct, original — pas de langue de bois
- Longueur : 200-250 mots
- Commence par une accroche forte et personnalisée (pas "Madame, Monsieur" générique)
- Adapte le contenu au TYPE de poste :
  * Data Scientist/ML → met en avant Python, pipelines, Claude API, agent IA
  * Data Engineer → met en avant ETL, pipelines, SQL, automatisation
  * AI Developer/IA → met en avant agent IA, LLM API, automatisation, bots
  * Dev Web → met en avant React, Node.js, JavaScript, projets web
  * Data Analyst → met en avant Power BI, KPI, tableaux de bord, EViews
- Si l'offre demande Bac+3 : mentionne "dès octobre 2026 je serai en 3e année (Bac+3)"
- Met en avant 2-3 éléments concrets du profil en lien direct avec CE poste
- Avant la signature, ajoute ce paragraphe EXACTEMENT :
  "PS : Ce message a été rédigé et envoyé par l'agent IA que j'ai développé pour automatiser ma recherche d'alternance. Pour plus de détails sur mon profil : GitHub → https://github.com/Alibenaqa | LinkedIn → https://www.linkedin.com/in/mohamed-ali-benaqa-209630264/ | Mon CV est joint à cet email."
- Signature : "Ali Benaqa | +33 6 67 67 79 37 | alibenaqa123@gmail.com"
- Réponds avec ce format exact :

OBJET: [sujet court et percutant, max 60 caractères]
---
[corps de l'email]"""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        texte = resp.content[0].text.strip()

        # Parser objet et corps
        objet = f"Candidature alternance – {offre['titre']} – Ali Benaqa"
        corps = texte

        if "OBJET:" in texte and "---" in texte:
            parties = texte.split("---", 1)
            ligne_objet = parties[0].strip()
            objet = ligne_objet.replace("OBJET:", "").strip()
            corps = parties[1].strip()

        return {"objet": objet, "corps": corps}
    except Exception as e:
        print(f"   ❌ Erreur génération email : {e}")
        return {
            "objet": f"Candidature alternance – {offre['titre']} – Ali Benaqa",
            "corps": f"Bonjour,\n\nJe me permets de vous contacter pour le poste {offre['titre']}.\n\nCordialement,\nAli Benaqa",
        }


# ────────────────────────────────────────────────
# CANDIDATURE VIA EMAIL (Hunter.io)
# ────────────────────────────────────────────────

def candidater_par_email(offre: dict, mem: Memory) -> bool:
    """Tente de postuler par email via Hunter.io. Retourne True si succès."""
    print(f"   📧 Recherche email pour {offre['entreprise']}...")
    contact = trouver_email_recruteur(offre["entreprise"])

    if not contact or not contact.get("email"):
        print(f"   ❌ Aucun email trouvé pour {offre['entreprise']}")
        return False

    email_rh = contact["email"]
    print(f"   ✅ Email trouvé : {email_rh} (confiance {contact['confiance']}%)")

    # Génère l'email
    email_data = generer_email_candidature(offre)

    # Envoie
    ok = envoyer_email(
        destinataire=email_rh,
        sujet=email_data["objet"],
        corps=email_data["corps"],
        offre_id=offre["id"],
    )

    if ok:
        mem.add_candidature({
            "offre_id": offre["id"],
            "canal": "email",
            "email_dest": email_rh,
            "objet_email": email_data["objet"],
            "corps_email": email_data["corps"],
            "date_relance": "datetime('now', '+7 days')",
        })
        mem.update_offre_statut(offre["id"], "postulé", f"Email envoyé à {email_rh}")

        # Notification Telegram
        notif = (
            f"✅ <b>J'ai postulé !</b>\n\n"
            f"🏢 <b>{offre['entreprise']}</b> — {offre['titre']}\n"
            f"📧 Mail envoyé à : <code>{email_rh}</code>\n\n"
            f"<b>Objet :</b> {email_data['objet']}\n\n"
            f"<b>Mail envoyé :</b>\n{email_data['corps'][:600]}\n\n"
            f"Tu en penses quoi ? 👆"
        )
        _telegram(notif)
        return True

    return False


# ────────────────────────────────────────────────
# CANDIDATURE VIA FORMULAIRE WTTJ (Playwright)
# ────────────────────────────────────────────────

def candidater_wttj(offre: dict, mem: Memory) -> bool:
    """Postule via le formulaire WTTJ avec Playwright."""
    if not offre.get("url") or "welcometothejungle" not in offre.get("url", ""):
        return False

    try:
        from playwright.sync_api import sync_playwright

        cv_path = Path(__file__).parent / "cv_ali.pdf"
        if not cv_path.exists():
            print(f"   ⚠️  cv_ali.pdf introuvable — impossible de postuler via formulaire")
            return False

        print(f"   🌐 Playwright → {offre['url']}")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(offre["url"], timeout=15000)
            page.wait_for_load_state("networkidle", timeout=10000)

            # Cherche le bouton "Postuler"
            btn = page.locator("a[href*='/apply'], button:has-text('Postuler'), a:has-text('Postuler')").first
            if not btn.is_visible():
                print(f"   ❌ Bouton Postuler introuvable")
                browser.close()
                return False

            btn.click()
            page.wait_for_load_state("networkidle", timeout=10000)

            # Remplir le formulaire
            for selector in ["input[name='email']", "input[type='email']"]:
                try:
                    page.fill(selector, "mohamedalibenaqa@gmail.com")
                    break
                except Exception:
                    pass

            for selector in ["input[name='firstName']", "input[placeholder*='rénom']"]:
                try:
                    page.fill(selector, "Mohamed Ali")
                    break
                except Exception:
                    pass

            for selector in ["input[name='lastName']", "input[placeholder*='om']"]:
                try:
                    page.fill(selector, "Benaqa")
                    break
                except Exception:
                    pass

            # Upload CV
            for selector in ["input[type='file']"]:
                try:
                    page.set_input_files(selector, str(cv_path))
                    break
                except Exception:
                    pass

            # Soumettre
            for selector in ["button[type='submit']:has-text('Envoyer')", "button:has-text('Postuler')"]:
                try:
                    page.click(selector)
                    page.wait_for_load_state("networkidle", timeout=8000)
                    break
                except Exception:
                    pass

            browser.close()

        mem.add_candidature({
            "offre_id": offre["id"],
            "canal": "formulaire_web",
            "email_dest": "",
            "objet_email": f"Candidature {offre['titre']}",
            "corps_email": "",
        })
        mem.update_offre_statut(offre["id"], "postulé", "Via formulaire WTTJ")

        # Notification Telegram
        notif = (
            f"✅ <b>J'ai postulé !</b>\n\n"
            f"🏢 <b>{offre['entreprise']}</b> — {offre['titre']}\n"
            f"🌐 Via formulaire WTTJ\n"
            f"🔗 {offre['url']}\n\n"
            f"CV envoyé directement sur leur plateforme 📄"
        )
        _telegram(notif)
        return True

    except ImportError:
        print("   ⚠️  Playwright non installé — skip formulaire")
        return False
    except Exception as e:
        print(f"   ❌ Erreur Playwright : {e}")
        return False


# ────────────────────────────────────────────────
# CYCLE CANDIDATURES AUTOMATIQUES
# ────────────────────────────────────────────────

def _entreprise_deja_contactee(entreprise: str, mem: Memory, jours: int = 30) -> bool:
    """Vérifie si on a déjà postulé à cette entreprise dans les X derniers jours."""
    if not entreprise:
        return False
    with mem._connect() as conn:
        row = conn.execute("""
            SELECT 1 FROM candidatures c
            JOIN offres o ON c.offre_id = o.id
            WHERE LOWER(o.entreprise) = LOWER(?)
              AND c.date_candidature >= datetime('now', ?)
        """, (entreprise.strip(), f"-{jours} days")).fetchone()
    return row is not None


def run_candidatures_auto() -> dict:
    """
    Postule automatiquement aux offres intéressantes non postulées.
    Retourne les stats du cycle.
    """
    from turso_sync import deja_postule_turso

    mem = Memory()
    offres = mem.get_offres_non_postulees(score_min=SCORE_MIN_AUTO)
    print(f"\n🤖 Candidatures auto — {len(offres)} offres éligibles (score>={SCORE_MIN_AUTO})")
    offres = offres[:MAX_CANDIDATURES]

    stats = {"email": 0, "formulaire": 0, "echecs": 0, "total": len(offres)}
    candidatures_envoyees = []

    for offre in offres:
        print(f"\n➡️  {offre['titre']} — {offre['entreprise']} ({int(offre['score_pertinence']*100)}%)")

        # ── Protection 1 : vérification Turso (source de vérité) ──
        if deja_postule_turso(offre["url"]):
            print(f"   ⏭️  Déjà postulé (Turso) — skip")
            mem.update_offre_statut(offre["id"], "postulé", "Déjà postulé (Turso sync)")
            continue

        # ── Protection 2 : même entreprise dans les 30 derniers jours ──
        if _entreprise_deja_contactee(offre["entreprise"], mem):
            print(f"   ⏭️  {offre['entreprise']} déjà contacté récemment — skip")
            mem.update_offre_statut(offre["id"], "ignoré", "Entreprise déjà contactée ce mois")
            continue

        # Tentative 1 : email via Hunter.io
        ok = candidater_par_email(offre, mem)
        if ok:
            stats["email"] += 1
            candidatures_envoyees.append({"titre": offre["titre"], "entreprise": offre["entreprise"], "canal": "email"})
            continue

        # Tentative 2 : formulaire WTTJ
        ok = candidater_wttj(offre, mem)
        if ok:
            stats["formulaire"] += 1
            candidatures_envoyees.append({"titre": offre["titre"], "entreprise": offre["entreprise"], "canal": "formulaire"})
        else:
            stats["echecs"] += 1

    return {**stats, "detail": candidatures_envoyees}


# ────────────────────────────────────────────────
# RÉSUMÉ QUOTIDIEN TELEGRAM
# ────────────────────────────────────────────────

def envoyer_resume_quotidien():
    """Envoie un résumé des candidatures du jour sur Telegram."""
    mem = Memory()
    stats = mem.get_stats()

    with mem._connect() as conn:
        # Candidatures du jour
        cands_jour = conn.execute("""
            SELECT c.canal, o.titre, o.entreprise, o.score_pertinence
            FROM candidatures c
            LEFT JOIN offres o ON c.offre_id = o.id
            WHERE date(c.date_candidature) = date('now')
            ORDER BY c.date_candidature DESC
        """).fetchall()

        # Réponses reçues
        reponses = conn.execute("""
            SELECT titre, entreprise, statut, notes
            FROM offres
            WHERE statut IN ('entretien', 'réponse')
              AND date(date_scrape) >= date('now', '-7 days')
        """).fetchall()

        # Offres intéressantes découvertes aujourd'hui
        offres_aujourd_hui = conn.execute("""
            SELECT COUNT(*) as nb FROM offres
            WHERE statut = 'intéressant'
              AND date(date_scrape) = date('now')
        """).fetchone()["nb"]

        # Répartition par source
        sources = conn.execute("""
            SELECT source, COUNT(*) as nb FROM offres
            WHERE statut = 'intéressant'
            GROUP BY source ORDER BY nb DESC
        """).fetchall()

    nb_cands = len(cands_jour)
    msg = f"📊 <b>Résumé du {datetime.now().strftime('%d/%m/%Y')}</b>\n\n"

    # Stats du jour
    msg += f"🔍 <b>Aujourd'hui :</b> {offres_aujourd_hui} nouvelles offres intéressantes\n"
    msg += f"📤 <b>Candidatures envoyées :</b> {nb_cands}\n"
    if nb_cands > 0:
        for c in cands_jour[:6]:
            canal_icon = {"email": "📧", "formulaire_web": "🌐", "linkedin_easy_apply": "🔗"}.get(c["canal"], "📤")
            pct = int((c["score_pertinence"] or 0) * 100)
            msg += f"  {canal_icon} {c['titre']} — {c['entreprise']} ({pct}%)\n"

    # Réponses
    if reponses:
        msg += f"\n📬 <b>Réponses reçues :</b>\n"
        for r in reponses:
            icon = "🎉" if r["statut"] == "entretien" else "📩"
            msg += f"  {icon} {r['entreprise']} — {r['statut']}\n"

    # Totaux globaux
    msg += f"\n─────────────────\n"
    msg += f"📈 Total : <b>{stats['total_candidatures']}</b> candidatures | <b>{stats['entretiens']}</b> entretiens\n"
    msg += f"Taux de réponse : <b>{stats.get('taux_reponse', 0)}%</b>\n"

    # Sources actives
    if sources:
        msg += f"\n📡 <b>Sources :</b> "
        msg += " | ".join(f"{s['source']} ({s['nb']})" for s in sources[:5])

    req.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
        timeout=10,
    )
    print("✅ Résumé quotidien envoyé sur Telegram")


def envoyer_stats_hebdo():
    """Envoie un bilan hebdomadaire complet chaque lundi sur Telegram."""
    mem = Memory()
    stats = mem.get_stats()

    with mem._connect() as conn:
        # Candidatures de la semaine
        cands_semaine = conn.execute("""
            SELECT c.canal, o.titre, o.entreprise, o.score_pertinence,
                   date(c.date_candidature) as jour
            FROM candidatures c
            LEFT JOIN offres o ON c.offre_id = o.id
            WHERE c.date_candidature >= datetime('now', '-7 days')
            ORDER BY c.date_candidature DESC
        """).fetchall()

        # Nouvelles offres cette semaine
        nb_offres_semaine = conn.execute("""
            SELECT COUNT(*) as nb FROM offres
            WHERE date_scrape >= datetime('now', '-7 days')
        """).fetchone()["nb"]

        nb_interessantes_semaine = conn.execute("""
            SELECT COUNT(*) as nb FROM offres
            WHERE statut = 'intéressant'
              AND date_scrape >= datetime('now', '-7 days')
        """).fetchone()["nb"]

        # Top offres de la semaine
        top_offres = conn.execute("""
            SELECT titre, entreprise, score_pertinence, source
            FROM offres
            WHERE statut = 'intéressant'
              AND date_scrape >= datetime('now', '-7 days')
            ORDER BY score_pertinence DESC LIMIT 5
        """).fetchall()

        # Répartition canaux cette semaine
        canaux = conn.execute("""
            SELECT canal, COUNT(*) as nb FROM candidatures
            WHERE date_candidature >= datetime('now', '-7 days')
            GROUP BY canal ORDER BY nb DESC
        """).fetchall()

        # Entretiens obtenus cette semaine
        entretiens_semaine = conn.execute("""
            SELECT o.entreprise, o.titre, c.date_candidature
            FROM offres o
            LEFT JOIN candidatures c ON c.offre_id = o.id
            WHERE o.statut = 'entretien'
              AND c.date_candidature >= datetime('now', '-7 days')
        """).fetchall()

        # Alumni contactés cette semaine
        alumni_semaine = conn.execute("""
            SELECT COUNT(*) as nb FROM alumni
            WHERE statut_contact = 'mail envoyé'
              AND date_contact >= datetime('now', '-7 days')
        """).fetchone()["nb"] if _table_existe(conn, "alumni") else 0

    nb_cands = len(cands_semaine)
    from datetime import datetime as dt
    semaine_str = dt.now().strftime("semaine du %d/%m/%Y")

    msg = f"📅 <b>Bilan hebdo — {semaine_str}</b>\n\n"

    # Chiffres clés
    msg += f"🔍 <b>Offres trouvées :</b> {nb_offres_semaine} total | {nb_interessantes_semaine} intéressantes\n"
    msg += f"📤 <b>Candidatures :</b> {nb_cands} cette semaine\n"
    if entretiens_semaine:
        msg += f"🎉 <b>Entretiens obtenus :</b> {len(entretiens_semaine)}\n"
        for e in entretiens_semaine:
            msg += f"  → {e['entreprise']} — {e['titre']}\n"
    msg += f"🎓 <b>Alumni contactés :</b> {alumni_semaine}\n"

    # Canaux utilisés
    if canaux:
        msg += f"\n📡 <b>Canaux :</b>\n"
        icons = {"email": "📧", "formulaire_web": "🌐", "linkedin_easy_apply": "🔗"}
        for c in canaux:
            msg += f"  {icons.get(c['canal'], '📤')} {c['canal']} : {c['nb']}\n"

    # Top 5 offres
    if top_offres:
        msg += f"\n🏆 <b>Top offres de la semaine :</b>\n"
        for o in top_offres:
            pct = int(o["score_pertinence"] * 100)
            emoji = "🔥" if pct >= 90 else "✅" if pct >= 80 else "👍"
            msg += f"  {emoji} {o['titre']} — {o['entreprise']} ({pct}%)\n"

    # Totaux cumulés
    msg += f"\n─────────────────\n"
    msg += f"📊 <b>Totaux cumulés :</b>\n"
    msg += f"  Candidatures : <b>{stats['total_candidatures']}</b>\n"
    msg += f"  Entretiens : <b>{stats['entretiens']}</b>\n"
    msg += f"  Taux réponse : <b>{stats.get('taux_reponse', 0)}%</b>\n"

    req.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
        timeout=10,
    )
    print("✅ Bilan hebdomadaire envoyé sur Telegram")


def _table_existe(conn, nom: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (nom,)
    ).fetchone()
    return row is not None


if __name__ == "__main__":
    stats = run_candidatures_auto()
    print(f"\n✅ Terminé — {stats['email']} emails, {stats['formulaire']} formulaires, {stats['echecs']} échecs")
