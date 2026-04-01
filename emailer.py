"""
emailer.py — Envoi et lecture d'emails via Gmail SMTP/IMAP
"""

import imaplib
import email
import os
import requests as req
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from datetime import datetime, timedelta

from memory import Memory

# ────────────────────────────────────────────────
# CONFIG
# ────────────────────────────────────────────────

GMAIL_ADDRESS  = os.environ.get("GMAIL_ADDRESS",  "mohamedalibenaqa@gmail.com")
GMAIL_PASSWORD = os.environ.get("GMAIL_PASSWORD", "nqus gjnt aohl kkue")
BREVO_API_KEY  = os.environ.get("BREVO_API_KEY", "")

IMAP_HOST = "imap.gmail.com"


# ────────────────────────────────────────────────
# ENVOI
# ────────────────────────────────────────────────

def envoyer_email(destinataire: str, sujet: str, corps: str, offre_id: int = None) -> bool:
    """
    Envoie un email via Brevo API (HTTP — fonctionne sur Railway).
    Retourne True si succès.
    """
    if not BREVO_API_KEY:
        print("   ❌ BREVO_API_KEY manquante")
        return False
    try:
        resp = req.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "api-key": BREVO_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "sender": {"name": "Ali Benaqa", "email": GMAIL_ADDRESS},
                "to": [{"email": destinataire}],
                "subject": sujet,
                "textContent": corps,
            },
            timeout=15,
        )
        if resp.status_code in (200, 201):
            mem = Memory()
            mem.log_email({
                "destinataire": destinataire,
                "objet": sujet,
                "corps": corps,
                "type_email": "candidature",
                "ref_id": offre_id,
                "ref_type": "offre",
            })
            print(f"   ✅ Email envoyé à {destinataire}")
            return True
        else:
            print(f"   ❌ Erreur Brevo : {resp.status_code} — {resp.text}")
            return False
    except Exception as e:
        print(f"   ❌ Erreur envoi email : {e}")
        return False


# ────────────────────────────────────────────────
# LECTURE DES RÉPONSES
# ────────────────────────────────────────────────

def lire_reponses(jours: int = 7) -> list[dict]:
    """
    Lit les emails non lus reçus dans les `jours` derniers.
    Retourne une liste de dict {from, subject, body, date}.
    """
    reponses = []
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST)
        mail.login(GMAIL_ADDRESS, GMAIL_PASSWORD)
        mail.select("inbox")

        depuis = (datetime.now() - timedelta(days=jours)).strftime("%d-%b-%Y")
        _, data = mail.search(None, f'(UNSEEN SINCE "{depuis}")')

        for num in data[0].split():
            _, msg_data = mail.fetch(num, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            # Décodage sujet
            sujet_raw, encoding = decode_header(msg["Subject"])[0]
            if isinstance(sujet_raw, bytes):
                sujet = sujet_raw.decode(encoding or "utf-8", errors="ignore")
            else:
                sujet = sujet_raw or ""

            # Décodage expéditeur
            expediteur = msg.get("From", "")

            # Corps
            corps = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        corps = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        break
            else:
                corps = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

            reponses.append({
                "from":    expediteur,
                "subject": sujet,
                "body":    corps[:1000],
                "date":    msg.get("Date", ""),
            })

        mail.logout()
    except Exception as e:
        print(f"   ❌ Erreur lecture emails : {e}")

    return reponses


# ────────────────────────────────────────────────
# VÉRIFICATION DES RÉPONSES (appelé par le cycle)
# ────────────────────────────────────────────────

def verifier_reponses_recruteurs() -> list[dict]:
    """
    Vérifie les emails non lus et filtre ceux qui semblent être des réponses recruteurs.
    Retourne les emails pertinents.
    """
    reponses = lire_reponses(jours=7)
    pertinents = []

    mots_cles = ["candidature", "alternance", "entretien", "poste", "profil",
                 "recrutement", "offre", "cv", "application", "interview"]

    for r in reponses:
        texte = (r["subject"] + " " + r["body"]).lower()
        if any(mot in texte for mot in mots_cles):
            pertinents.append(r)

    return pertinents


if __name__ == "__main__":
    print("Test envoi email...")
    ok = envoyer_email(
        destinataire=GMAIL_ADDRESS,
        sujet="Test bot alternance",
        corps="Si tu reçois ce mail, l'envoi automatique fonctionne ✅",
    )
    print("Succès !" if ok else "Échec.")
