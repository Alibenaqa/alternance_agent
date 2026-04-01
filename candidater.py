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

    prompt = f"""Rédige un email de candidature pour Ali Benaqa.

PROFIL ALI :
- Formation : Bachelor Data & IA — Hetic (3e année, oct 2026)
- Expériences : Data Analyst chez Techwin et BNC Corporation, Stage Mamda Assurance
- Stack : Python, SQL, Power BI, ETL, API REST, Machine Learning
- Disponibilité : {r['disponibilite']} | Durée : {r['duree_contrat']}

OFFRE CIBLÉE :
- Poste : {offre['titre']}
- Entreprise : {offre['entreprise']}
- Localisation : {offre['localisation']}
- Description : {(offre.get('description') or 'N/A')[:600]}

INSTRUCTIONS :
- Style : professionnel mais naturel, direct
- Longueur : 150-180 mots max
- Met en avant 2-3 expériences data pertinentes pour CE poste
- Mentionne Hetic (école reconnue data/IA)
- Termine par une phrase d'appel à l'action (entretien)
- Réponds avec ce format exact :

OBJET: [sujet de l'email ici]
---
[corps de l'email ici]"""

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

def run_candidatures_auto() -> dict:
    """
    Postule automatiquement aux offres intéressantes non postulées.
    Retourne les stats du cycle.
    """
    mem = Memory()
    offres = mem.get_offres_non_postulees(score_min=SCORE_MIN_AUTO)
    offres = offres[:MAX_CANDIDATURES]  # limite de sécurité

    stats = {"email": 0, "formulaire": 0, "echecs": 0, "total": len(offres)}
    candidatures_envoyees = []

    print(f"\n🤖 Candidatures auto — {len(offres)} offres à traiter...")

    for offre in offres:
        print(f"\n➡️  {offre['titre']} — {offre['entreprise']} ({int(offre['score_pertinence']*100)}%)")

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

    # Candidatures du jour
    with mem._connect() as conn:
        cands_jour = conn.execute("""
            SELECT c.objet_email, c.email_dest, c.canal, o.titre, o.entreprise
            FROM candidatures c
            LEFT JOIN offres o ON c.offre_id = o.id
            WHERE date(c.date_candidature) = date('now')
            ORDER BY c.date_candidature DESC
        """).fetchall()

        # Réponses reçues (offres passées en statut réponse/entretien)
        reponses = conn.execute("""
            SELECT titre, entreprise, statut, notes
            FROM offres
            WHERE statut IN ('entretien', 'réponse')
              AND date(date_scrape) >= date('now', '-7 days')
        """).fetchall()

    # Construire le message
    nb_cands = len(cands_jour)
    msg = f"📊 <b>Résumé du {datetime.now().strftime('%d/%m/%Y')}</b>\n\n"

    if nb_cands > 0:
        msg += f"📤 <b>{nb_cands} candidature(s) envoyée(s) aujourd'hui :</b>\n"
        for c in cands_jour[:8]:
            canal_icon = "📧" if c["canal"] == "email" else "🌐"
            msg += f"  {canal_icon} {c['titre']} — {c['entreprise']}\n"
    else:
        msg += "📤 Aucune candidature envoyée aujourd'hui.\n"

    if reponses:
        msg += f"\n📬 <b>Réponses reçues :</b>\n"
        for r in reponses:
            icon = "🎉" if r["statut"] == "entretien" else "📩"
            msg += f"  {icon} {r['entreprise']} — {r['statut']}\n"

    msg += f"\n📈 Total : {stats['total_candidatures']} candidatures | {stats['entretiens']} entretiens"

    req.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
        timeout=10,
    )
    print("✅ Résumé quotidien envoyé sur Telegram")


if __name__ == "__main__":
    stats = run_candidatures_auto()
    print(f"\n✅ Terminé — {stats['email']} emails, {stats['formulaire']} formulaires, {stats['echecs']} échecs")
