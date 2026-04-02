"""
emailer.py — Envoi et lecture d'emails via Gmail API (OAuth2)
Fonctionne sur Railway (HTTP, jamais bloqué).
"""

import os
import base64
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.application import MIMEApplication
from email.header import decode_header
from datetime import datetime, timedelta
from pathlib import Path

import requests as req
from memory import Memory

CV_PATH = Path(__file__).parent / "cv_ali.pdf"

# ────────────────────────────────────────────────
# CONFIG
# ────────────────────────────────────────────────

GMAIL_ADDRESS      = os.environ.get("GMAIL_ADDRESS", "mohamedalibenaqa@gmail.com")
GMAIL_PASSWORD     = os.environ.get("GMAIL_PASSWORD", "nqus gjnt aohl kkue")
GMAIL_CLIENT_ID    = os.environ.get("GMAIL_CLIENT_ID", "243098298551-dt7dtfcc6odnnslkn67gnpmt8ukl3kf5.apps.googleusercontent.com")
GMAIL_CLIENT_SECRET = os.environ.get("GMAIL_CLIENT_SECRET", "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")
GMAIL_REFRESH_TOKEN = os.environ.get("GMAIL_REFRESH_TOKEN", "1//03WnaB4BhthJnCgYIARAAGAMSNwF-L9Ir7mr4pCyX-ZiNDMRpzpVs9-HYnz4Lw4GZkcYbr-fkLMAFmR8vxywwtzbBdJgLJoiJ__Y")

IMAP_HOST = "imap.gmail.com"


# ────────────────────────────────────────────────
# OAUTH2 — Obtenir un access token
# ────────────────────────────────────────────────

def _get_access_token() -> str | None:
    """Échange le refresh token contre un access token frais."""
    try:
        resp = req.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": GMAIL_CLIENT_ID,
                "client_secret": GMAIL_CLIENT_SECRET,
                "refresh_token": GMAIL_REFRESH_TOKEN,
                "grant_type": "refresh_token",
            },
            timeout=10,
        )
        return resp.json().get("access_token")
    except Exception as e:
        print(f"   ❌ Erreur OAuth2 : {e}")
        return None


# ────────────────────────────────────────────────
# ENVOI VIA GMAIL API
# ────────────────────────────────────────────────

def envoyer_email(destinataire: str, sujet: str, corps: str, offre_id: int = None) -> bool:
    """
    Envoie un email via Gmail API (OAuth2 — fonctionne sur Railway).
    Retourne True si succès.
    """
    access_token = _get_access_token()
    if not access_token:
        print("   ❌ Impossible d'obtenir un access token Gmail")
        return False

    try:
        msg = MIMEMultipart()
        msg["From"]    = f"Ali Benaqa <{GMAIL_ADDRESS}>"
        msg["To"]      = destinataire
        msg["Bcc"]     = GMAIL_ADDRESS
        msg["Subject"] = sujet

        msg.attach(MIMEText(corps, "plain", "utf-8"))

        # Pièce jointe CV PDF
        if CV_PATH.exists():
            with open(CV_PATH, "rb") as f:
                cv_part = MIMEApplication(f.read(), _subtype="pdf")
                cv_part.add_header("Content-Disposition", "attachment", filename="CV_Ali_Benaqa.pdf")
                msg.attach(cv_part)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

        resp = req.post(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"raw": raw},
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
            print(f"   ❌ Erreur Gmail API : {resp.status_code} — {resp.text[:200]}")
            return False

    except Exception as e:
        print(f"   ❌ Erreur envoi email : {e}")
        return False


# ────────────────────────────────────────────────
# LECTURE DES RÉPONSES VIA IMAP
# ────────────────────────────────────────────────

def _ids_deja_traites() -> set:
    """Retourne les message-IDs déjà traités (stockés en DB locale)."""
    try:
        mem = Memory()
        with mem._connect() as conn:
            rows = conn.execute(
                "SELECT objet FROM emails_log WHERE type_email = 'reponse_traitee'"
            ).fetchall()
            return {str(r[0]) for r in rows}
    except Exception:
        return set()


def _marquer_traite(message_id: str):
    """Marque un message-ID comme traité pour ne pas le retraiter au prochain cycle."""
    if not message_id:
        return
    try:
        mem = Memory()
        mem.log_email({
            "destinataire": "inbox",
            "objet": message_id,
            "corps": "",
            "type_email": "reponse_traitee",
            "ref_id": None,
            "ref_type": "inbox",
        })
    except Exception:
        pass


def lire_reponses(jours: int = 3) -> list[dict]:
    """
    Lit les emails reçus dans les `jours` derniers — lus ET non-lus.
    Filtre uniquement ceux pas encore traités (via message-ID en DB).
    """
    reponses = []
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST)
        mail.login(GMAIL_ADDRESS, GMAIL_PASSWORD)
        mail.select("inbox")

        depuis = (datetime.now() - timedelta(days=jours)).strftime("%d-%b-%Y")
        # Cherche TOUS les emails récents (SEEN + UNSEEN) — pas seulement non-lus
        _, data = mail.search(None, f'SINCE "{depuis}"')

        deja_traites = _ids_deja_traites()

        for num in data[0].split():
            _, msg_data = mail.fetch(num, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            # Identifiant unique de cet email
            message_id = msg.get("Message-ID", str(num))

            # Skip si déjà traité
            if message_id in deja_traites:
                continue

            sujet_raw, encoding = decode_header(msg["Subject"] or "")[0]
            if isinstance(sujet_raw, bytes):
                sujet = sujet_raw.decode(encoding or "utf-8", errors="ignore")
            else:
                sujet = sujet_raw or ""

            expediteur = msg.get("From", "")

            # Skip nos propres emails envoyés (BCC)
            if GMAIL_ADDRESS in expediteur:
                continue

            corps = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        try:
                            corps = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                            break
                        except Exception:
                            pass
            else:
                try:
                    corps = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                except Exception:
                    pass

            reponses.append({
                "message_id": message_id,
                "from": expediteur,
                "subject": sujet,
                "body": corps[:1500],
                "date": msg.get("Date", ""),
                "in_reply_to": msg.get("In-Reply-To", ""),
            })

        mail.logout()
    except Exception as e:
        print(f"   ❌ Erreur lecture emails IMAP : {e}")

    return reponses


def verifier_reponses_recruteurs() -> list[dict]:
    """
    Filtre les emails reçus qui semblent être des réponses recruteurs.
    Détecte : réponses à nos mails (Re:), mots-clés candidature, et emails directs.
    """
    reponses = lire_reponses(jours=3)

    mots_cles_forts = [
        "candidature", "alternance", "entretien", "recrutement",
        "offre", "cv", "application", "interview", "poste",
        "profil", "opportunité", "dossier",
    ]
    mots_cles_reponse = [
        "merci", "intéresse", "retenu", "sélectionné", "disponible",
        "rappeler", "rencontrer", "échange", "appel", "convoqué",
        "malheureusement", "suite", "retour", "réponse",
    ]

    pertinents = []
    for r in reponses:
        texte = (r["subject"] + " " + r["body"]).lower()
        sujet = r["subject"].lower()

        # C'est une réponse à un de nos emails (Re: dans le sujet)
        est_reply = sujet.startswith("re:") or sujet.startswith("rép:") or r.get("in_reply_to")

        # Contient des mots-clés forts
        a_mots_forts = any(mot in texte for mot in mots_cles_forts)

        # Contient des mots de réponse (intérêt, refus, suite...)
        a_mots_reponse = any(mot in texte for mot in mots_cles_reponse)

        if est_reply or a_mots_forts or (a_mots_reponse and len(r["body"]) > 50):
            pertinents.append(r)

    return pertinents


if __name__ == "__main__":
    print("Test envoi Gmail API...")
    ok = envoyer_email(
        destinataire=GMAIL_ADDRESS,
        sujet="Test Gmail API — bot alternance",
        corps="Si tu reçois ce mail, Gmail API fonctionne ✅",
    )
    print("Succès !" if ok else "Échec.")
