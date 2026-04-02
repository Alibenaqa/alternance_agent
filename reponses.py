"""
reponses.py — Lecture des réponses recruteurs + relances automatiques

Fonctionnalités :
1. Lit les emails non lus → détecte les réponses recruteurs
2. Claude analyse chaque réponse (positif/négatif/entretien) + suggère quoi répondre
3. Notifie Telegram avec le contenu + analyse
4. Met à jour le statut de l'offre en base
5. Envoie des relances auto aux candidatures sans réponse depuis 7 jours
"""

import os
import json
import requests as req
from datetime import datetime

import anthropic

from memory import Memory
from emailer import verifier_reponses_recruteurs, envoyer_email, _marquer_traite

TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "8658482373:AAH3Oxk6of_JWCVXRBXn_L4X9cIaHHMcDrc")
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "7026975488")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


def _telegram(texte: str):
    try:
        req.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": texte, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass


# ────────────────────────────────────────────────
# ANALYSE CLAUDE D'UNE RÉPONSE RECRUTEUR
# ────────────────────────────────────────────────

def _extraire_date_entretien(texte: str) -> str | None:
    """Extrait une date/heure d'entretien depuis un texte via regex."""
    import re
    patterns = [
        r'\b(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})\b',          # 15/04/2026
        r'\b(\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+\d{4})\b',
        r'\b(lundi|mardi|mercredi|jeudi|vendredi)\s+\d{1,2}\s+\w+',
        r'\b(\d{1,2}h(?:\d{2})?)\b',                              # 14h00
    ]
    for p in patterns:
        m = re.search(p, texte, re.IGNORECASE)
        if m:
            return m.group(0)
    return None


def analyser_reponse(email: dict) -> dict:
    """
    Claude analyse un email recruteur.
    Retourne : {type, résumé, suggestion_réponse, statut_offre}
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""Tu es l'assistant d'Ali Benaqa, étudiant en Bachelor Data & IA à Hetic, qui cherche une alternance.
Il vient de recevoir cet email d'un recruteur :

DE : {email.get('from', '')}
OBJET : {email.get('subject', '')}
DATE : {email.get('date', '')}
CORPS :
{email.get('body', '')[:1500]}

Analyse cet email et réponds en JSON uniquement avec ces champs :
{{
  "type": "entretien" | "positif" | "negatif" | "en_attente" | "autre",
  "resume": "résumé en 1 phrase de ce que dit le recruteur",
  "urgence": "haute" | "normale" | "faible",
  "suggestion_reponse": "brouillon de réponse en 3-4 lignes max, chaleureux et pro, signé Ali Benaqa",
  "statut_offre": "entretien" | "réponse" | "refusé" | null
}}

Types :
- "entretien" = convoque à un entretien / appel
- "positif" = intéressé mais pas encore d'entretien
- "negatif" = refus
- "en_attente" = accusé réception, dossier en cours
- "autre" = hors sujet, spam, auto-reply

Ne réponds qu'avec le JSON, rien d'autre."""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        texte = resp.content[0].text.strip()
        # Nettoie les blocs ```json si présents
        texte = texte.replace("```json", "").replace("```", "").strip()
        return json.loads(texte)
    except Exception as e:
        print(f"   ❌ Erreur analyse Claude : {e}")
        return {
            "type": "autre",
            "resume": "Impossible d'analyser",
            "urgence": "normale",
            "suggestion_reponse": "",
            "statut_offre": None,
        }


def _trouver_offre_par_expediteur(email_from: str, mem: Memory) -> dict | None:
    """Cherche l'offre associée à un email recruteur via le domaine."""
    domaine = email_from.split("@")[-1].replace(">", "").strip() if "@" in email_from else ""
    if not domaine:
        return None
    with mem._connect() as conn:
        row = conn.execute("""
            SELECT o.* FROM offres o
            JOIN candidatures c ON c.offre_id = o.id
            WHERE c.email_dest LIKE ?
              AND o.statut = 'postulé'
            ORDER BY c.date_candidature DESC
            LIMIT 1
        """, (f"%{domaine}%",)).fetchone()
    return dict(row) if row else None


# ────────────────────────────────────────────────
# LECTURE ET TRAITEMENT DES RÉPONSES
# ────────────────────────────────────────────────

def traiter_reponses_recruteurs() -> int:
    """
    Lit les emails non lus, détecte les réponses recruteurs,
    analyse avec Claude et notifie Telegram.
    Retourne le nombre de réponses traitées.
    """
    print("\n📬 Lecture des réponses recruteurs...")
    mem = Memory()

    emails = verifier_reponses_recruteurs()
    if not emails:
        print("   ℹ️  Aucune nouvelle réponse recruteur")
        return 0

    print(f"   → {len(emails)} réponse(s) détectée(s)")
    nb_traites = 0

    for email in emails:
        print(f"\n   📧 De : {email.get('from', '')} | Objet : {email.get('subject', '')[:50]}")

        analyse = analyser_reponse(email)
        type_rep = analyse.get("type", "autre")

        # Marque toujours comme traité (même si "autre") pour ne pas retraiter
        _marquer_traite(email.get("message_id", ""))

        if type_rep == "autre":
            print(f"   ⏭️  Email non pertinent, ignoré")
            continue

        # Icône selon le type
        icons = {
            "entretien":  "🎉",
            "positif":    "😊",
            "negatif":    "😔",
            "en_attente": "⏳",
        }
        icon = icons.get(type_rep, "📩")

        # Met à jour le statut de l'offre si possible
        offre = _trouver_offre_par_expediteur(email.get("from", ""), mem)
        if offre and analyse.get("statut_offre"):
            mem.update_offre_statut(offre["id"], analyse["statut_offre"], analyse.get("resume", ""))
            print(f"   ✅ Offre mise à jour → {analyse['statut_offre']}")

        # Détection date d'entretien
        date_entretien = None
        if type_rep == "entretien":
            date_entretien = _extraire_date_entretien(email.get("body", "") + email.get("subject", ""))

        # Notification Telegram
        msg = (
            f"{icon} <b>Réponse recruteur !</b>\n\n"
            f"📧 <b>De :</b> {email.get('from', '')}\n"
            f"📋 <b>Objet :</b> {email.get('subject', '')}\n\n"
            f"<b>Résumé :</b> {analyse.get('resume', '')}\n"
        )

        if offre:
            msg += f"\n<b>Offre :</b> {offre.get('titre', '')} chez {offre.get('entreprise', '')}\n"

        if date_entretien:
            msg += f"\n📅 <b>Date détectée : {date_entretien}</b> — Pense à confirmer !\n"

        if analyse.get("suggestion_reponse"):
            msg += (
                f"\n💬 <b>Suggestion de réponse :</b>\n"
                f"<i>{analyse['suggestion_reponse']}</i>\n"
            )

        if analyse.get("urgence") == "haute":
            msg += "\n⚡ <b>À traiter rapidement !</b>"

        _telegram(msg)

        # Si entretien détecté → ajoute au calendrier iCloud
        if type_rep == "entretien":
            try:
                from calendrier import planifier_entretien
                entreprise = offre.get("entreprise", "") if offre else email.get("from", "")
                poste      = offre.get("titre", "") if offre else email.get("subject", "")
                planifier_entretien(
                    entreprise=entreprise,
                    poste=poste,
                    texte_email=email.get("body", "") + " " + email.get("subject", ""),
                )
            except Exception as e:
                print(f"   ⚠️  Calendrier : {e}")

        nb_traites += 1

    print(f"   ✅ {nb_traites} réponse(s) traitée(s)")
    return nb_traites


# ────────────────────────────────────────────────
# RELANCES AUTOMATIQUES
# ────────────────────────────────────────────────

def _generer_email_relance(offre: dict, candidature: dict) -> dict:
    """Génère un email de relance poli via Claude."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    nb = candidature.get("nb_relances", 0) + 1

    prompt = f"""Rédige un email de relance court et poli de la part d'Ali Benaqa.

CONTEXTE :
Ali a postulé il y a environ 7 jours pour ce poste et n'a pas eu de réponse.
C'est sa {nb}e relance.

POSTE : {offre.get('titre', '')}
ENTREPRISE : {offre.get('entreprise', '')}
EMAIL ORIGINAL envoyé : {candidature.get('objet_email', '')}

INSTRUCTIONS :
- 3-4 lignes MAX, très court
- Rappelle sa candidature et son intérêt pour le poste
- Demande si le dossier a bien été reçu
- Reste positif et pro, pas insistant
- Signature : "Ali Benaqa | Hetic Bachelor Data & IA | +33 6 67 67 79 37"
- Format :

OBJET: [objet court]
---
[corps]"""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=250,
            messages=[{"role": "user", "content": prompt}],
        )
        texte = resp.content[0].text.strip()

        objet = f"Relance — {offre.get('titre', '')} — Ali Benaqa"
        corps = texte

        if "OBJET:" in texte and "---" in texte:
            parties = texte.split("---", 1)
            objet = parties[0].replace("OBJET:", "").strip()
            corps = parties[1].strip()

        return {"objet": objet, "corps": corps}
    except Exception as e:
        print(f"   ❌ Erreur génération relance : {e}")
        return {
            "objet": f"Relance candidature — {offre.get('titre', '')}",
            "corps": (
                f"Bonjour,\n\nJe me permets de relancer ma candidature pour le poste de "
                f"{offre.get('titre', '')} envoyée il y a quelques jours.\n\n"
                f"Mon dossier a-t-il bien été reçu ?\n\n"
                f"Cordialement,\nAli Benaqa | +33 6 67 67 79 37"
            ),
        }


def envoyer_relances_auto() -> int:
    """
    Envoie des emails de relance aux candidatures sans réponse depuis 7 jours.
    Max 2 relances par candidature.
    Retourne le nombre de relances envoyées.
    """
    print("\n🔄 Vérification des relances automatiques...")
    mem = Memory()
    a_relancer = mem.get_candidatures_a_relancer()

    if not a_relancer:
        print("   ℹ️  Aucune relance à envoyer")
        return 0

    print(f"   → {len(a_relancer)} candidature(s) à relancer")
    nb_relances = 0

    for cand in a_relancer:
        email_dest = cand.get("email_dest", "")
        if not email_dest:
            continue

        print(f"\n   🔄 Relance : {cand.get('titre', '?')} — {cand.get('entreprise', '?')}")

        # Récupère l'offre
        with mem._connect() as conn:
            offre = conn.execute(
                "SELECT * FROM offres WHERE id = ?", (cand["offre_id"],)
            ).fetchone()
        if not offre:
            continue
        offre = dict(offre)

        email_data = _generer_email_relance(offre, cand)

        ok = envoyer_email(
            destinataire=email_dest,
            sujet=email_data["objet"],
            corps=email_data["corps"],
            offre_id=offre["id"],
        )

        if ok:
            # Met à jour la candidature
            with mem._connect() as conn:
                conn.execute("""
                    UPDATE candidatures
                    SET nb_relances = nb_relances + 1,
                        date_relance = datetime('now', '+7 days'),
                        statut = 'relance'
                    WHERE id = ?
                """, (cand["id"],))

            nb_relances += 1

            _telegram(
                f"🔄 <b>Relance envoyée</b>\n\n"
                f"🏢 {offre.get('entreprise', '')} — {offre.get('titre', '')}\n"
                f"📧 À : <code>{email_dest}</code>\n"
                f"<b>Objet :</b> {email_data['objet']}"
            )
        else:
            print(f"   ❌ Échec relance pour {email_dest}")

    print(f"   ✅ {nb_relances} relance(s) envoyée(s)")
    return nb_relances


# ────────────────────────────────────────────────
# POINT D'ENTRÉE
# ────────────────────────────────────────────────

def run_suivi_candidatures() -> dict:
    """Lance la lecture des réponses + les relances auto."""
    nb_reponses = traiter_reponses_recruteurs()
    nb_relances = envoyer_relances_auto()
    return {"reponses": nb_reponses, "relances": nb_relances}


if __name__ == "__main__":
    stats = run_suivi_candidatures()
    print(f"\n📊 Résultat : {stats['reponses']} réponse(s) traitée(s), {stats['relances']} relance(s) envoyée(s)")
