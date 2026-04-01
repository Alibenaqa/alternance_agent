"""
emailer.py — Envoi et lecture d'emails via Gmail API (OAuth2)
Fonctionne sur Railway (HTTP, jamais bloqué).
"""

import os
import base64
import imaplib
import email
from email.mime.text import MIMEText
from email.header import decode_header
from datetime import datetime, timedelta

import requests as req
from memory import Memory

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
        msg = MIMEText(corps, "plain", "utf-8")
        msg["From"]    = f"Ali Benaqa <{GMAIL_ADDRESS}>"
        msg["To"]      = destinataire
        msg["Bcc"]     = GMAIL_ADDRESS
        msg["Subject"] = sujet

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

def lire_reponses(jours: int = 7) -> list[dict]:
    """Lit les emails non lus reçus dans les `jours` derniers."""
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

            sujet_raw, encoding = decode_header(msg["Subject"])[0]
            if isinstance(sujet_raw, bytes):
                sujet = sujet_raw.decode(encoding or "utf-8", errors="ignore")
            else:
                sujet = sujet_raw or ""

            expediteur = msg.get("From", "")
            corps = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        corps = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        break
            else:
                corps = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

            reponses.append({
                "from": expediteur,
                "subject": sujet,
                "body": corps[:1000],
                "date": msg.get("Date", ""),
            })

        mail.logout()
    except Exception as e:
        print(f"   ❌ Erreur lecture emails : {e}")

    return reponses


def verifier_reponses_recruteurs() -> list[dict]:
    """Filtre les emails non lus qui semblent être des réponses recruteurs."""
    reponses = lire_reponses(jours=7)
    mots_cles = ["candidature", "alternance", "entretien", "poste", "profil",
                 "recrutement", "offre", "cv", "application", "interview"]
    return [
        r for r in reponses
        if any(mot in (r["subject"] + r["body"]).lower() for mot in mots_cles)
    ]


if __name__ == "__main__":
    print("Test envoi Gmail API...")
    ok = envoyer_email(
        destinataire=GMAIL_ADDRESS,
        sujet="Test Gmail API — bot alternance",
        corps="Si tu reçois ce mail, Gmail API fonctionne ✅",
    )
    print("Succès !" if ok else "Échec.")
