"""
calendrier.py — Ajout d'événements dans le calendrier iCloud (iPhone)
Utilise le protocole CalDAV pour créer des événements directement.

Variables Railway à ajouter :
  ICLOUD_EMAIL        → ton Apple ID (ex: ali@icloud.com ou Gmail lié à Apple)
  ICLOUD_APP_PASSWORD → mot de passe d'app généré sur appleid.apple.com

Comment générer le mot de passe d'app :
  1. appleid.apple.com → Connexion
  2. Sécurité → Mots de passe pour les apps
  3. Générer → copier le format xxxx-xxxx-xxxx-xxxx
"""

import os
import re
import uuid
from datetime import datetime, timedelta

import requests as req

ICLOUD_EMAIL        = os.environ.get("ICLOUD_EMAIL", "")
ICLOUD_APP_PASSWORD = os.environ.get("ICLOUD_APP_PASSWORD", "")

CALDAV_URL = "https://caldav.icloud.com"

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "8658482373:AAH3Oxk6of_JWCVXRBXn_L4X9cIaHHMcDrc")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "7026975488")

MOIS_FR = {
    "janvier": 1, "février": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
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


# ────────────────────────────────────────────────
# PARSING DE DATE DEPUIS UN TEXTE D'EMAIL
# ────────────────────────────────────────────────

def extraire_datetime(texte: str) -> datetime | None:
    """
    Extrait une date et heure depuis un texte d'email recruteur.
    Supporte les formats français courants.
    """
    texte_lower = texte.lower()

    # ── Format : "15 avril 2026 à 14h00" ─────────────────────
    m = re.search(
        r'(\d{1,2})\s+(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+(\d{4})'
        r'(?:\s+[àa]\s+(\d{1,2})h(\d{2})?)?',
        texte_lower
    )
    if m:
        jour   = int(m.group(1))
        mois   = MOIS_FR.get(m.group(2), 1)
        annee  = int(m.group(3))
        heure  = int(m.group(4)) if m.group(4) else 10
        minute = int(m.group(5)) if m.group(5) else 0
        try:
            return datetime(annee, mois, jour, heure, minute)
        except ValueError:
            pass

    # ── Format : "15/04/2026 à 14h00" ────────────────────────
    m = re.search(
        r'(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})'
        r'(?:\s+[àa]\s+(\d{1,2})h(\d{2})?)?',
        texte
    )
    if m:
        jour   = int(m.group(1))
        mois   = int(m.group(2))
        annee  = int(m.group(3))
        heure  = int(m.group(4)) if m.group(4) else 10
        minute = int(m.group(5)) if m.group(5) else 0
        try:
            return datetime(annee, mois, jour, heure, minute)
        except ValueError:
            pass

    # ── Format : "lundi 15 avril à 14h" ──────────────────────
    m = re.search(
        r'(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+'
        r'(\d{1,2})\s+(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)'
        r'(?:\s+(\d{4}))?(?:\s+[àa]\s+(\d{1,2})h(\d{2})?)?',
        texte_lower
    )
    if m:
        jour   = int(m.group(1))
        mois   = MOIS_FR.get(m.group(2), 1)
        annee  = int(m.group(3)) if m.group(3) else datetime.now().year
        heure  = int(m.group(4)) if m.group(4) else 10
        minute = int(m.group(5)) if m.group(5) else 0
        try:
            return datetime(annee, mois, jour, heure, minute)
        except ValueError:
            pass

    return None


# ────────────────────────────────────────────────
# CRÉATION D'ÉVÉNEMENT iCAL (format .ics)
# ────────────────────────────────────────────────

def _creer_ical(titre: str, debut: datetime, description: str = "", duree_min: int = 60) -> str:
    """Génère le contenu d'un fichier iCal (.ics) pour un événement."""
    fin = debut + timedelta(minutes=duree_min)
    uid = str(uuid.uuid4())
    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    debut_str = debut.strftime("%Y%m%dT%H%M%S")
    fin_str   = fin.strftime("%Y%m%dT%H%M%S")

    # Nettoie la description pour iCal
    desc_clean = description.replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")[:500]

    return f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//AlternanceAgent//Bot//FR
BEGIN:VEVENT
UID:{uid}
DTSTAMP:{now}
DTSTART:{debut_str}
DTEND:{fin_str}
SUMMARY:{titre}
DESCRIPTION:{desc_clean}
LOCATION:À confirmer avec le recruteur
STATUS:TENTATIVE
BEGIN:VALARM
TRIGGER:-PT1H
ACTION:DISPLAY
DESCRIPTION:Rappel entretien dans 1h
END:VALARM
BEGIN:VALARM
TRIGGER:-PT24H
ACTION:DISPLAY
DESCRIPTION:Entretien demain !
END:VALARM
END:VEVENT
END:VCALENDAR"""


# ────────────────────────────────────────────────
# ENVOI VIA CALDAV ICLOUD
# ────────────────────────────────────────────────

def _get_calendar_url() -> str | None:
    """Découvre l'URL du calendrier principal iCloud via PROPFIND."""
    try:
        # Étape 1 : trouver le principal
        resp = req.request(
            "PROPFIND",
            f"{CALDAV_URL}/",
            auth=(ICLOUD_EMAIL, ICLOUD_APP_PASSWORD),
            headers={
                "Depth": "0",
                "Content-Type": "application/xml",
            },
            data="""<?xml version="1.0" encoding="UTF-8"?>
<d:propfind xmlns:d="DAV:">
  <d:prop>
    <d:current-user-principal/>
  </d:prop>
</d:propfind>""",
            timeout=15,
        )

        # Extrait le principal-url
        m = re.search(r'<d:href>(/[^<]+)</d:href>', resp.text)
        if not m:
            return None
        principal = m.group(1)

        # Étape 2 : trouver le home-set
        resp2 = req.request(
            "PROPFIND",
            f"https://caldav.icloud.com{principal}",
            auth=(ICLOUD_EMAIL, ICLOUD_APP_PASSWORD),
            headers={"Depth": "0", "Content-Type": "application/xml"},
            data="""<?xml version="1.0" encoding="UTF-8"?>
<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <c:calendar-home-set/>
  </d:prop>
</d:propfind>""",
            timeout=15,
        )

        m2 = re.search(r'calendar-home-set.*?<d:href>(/[^<]+)</d:href>', resp2.text, re.DOTALL)
        if not m2:
            return None
        home = m2.group(1)

        # Étape 3 : trouver le premier calendrier
        resp3 = req.request(
            "PROPFIND",
            f"https://caldav.icloud.com{home}",
            auth=(ICLOUD_EMAIL, ICLOUD_APP_PASSWORD),
            headers={"Depth": "1", "Content-Type": "application/xml"},
            data="""<?xml version="1.0" encoding="UTF-8"?>
<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <d:resourcetype/>
    <d:displayname/>
  </d:prop>
</d:propfind>""",
            timeout=15,
        )

        # Prend le premier calendrier trouvé
        calendriers = re.findall(r'<d:href>(/[^<]+/)</d:href>', resp3.text)
        for cal in calendriers:
            if cal != home and cal.endswith("/"):
                return f"https://caldav.icloud.com{cal}"

        return None

    except Exception as e:
        print(f"   ❌ CalDAV discovery : {e}")
        return None


def ajouter_evenement_calendrier(
    titre: str,
    debut: datetime,
    description: str = "",
    duree_min: int = 60,
) -> bool:
    """
    Ajoute un événement dans le calendrier iCloud d'Ali.
    Retourne True si succès.
    """
    if not ICLOUD_EMAIL or not ICLOUD_APP_PASSWORD:
        print("   ⚠️  ICLOUD_EMAIL ou ICLOUD_APP_PASSWORD manquant")
        return False

    try:
        cal_url = _get_calendar_url()
        if not cal_url:
            print("   ❌ Impossible de trouver le calendrier iCloud")
            return False

        ical_content = _creer_ical(titre, debut, description, duree_min)
        event_uid    = str(uuid.uuid4())
        event_url    = f"{cal_url}{event_uid}.ics"

        resp = req.put(
            event_url,
            auth=(ICLOUD_EMAIL, ICLOUD_APP_PASSWORD),
            headers={"Content-Type": "text/calendar; charset=utf-8"},
            data=ical_content.encode("utf-8"),
            timeout=15,
        )

        if resp.status_code in (200, 201, 204):
            print(f"   ✅ Événement ajouté au calendrier : {titre} le {debut.strftime('%d/%m/%Y à %Hh%M')}")
            return True
        else:
            print(f"   ❌ CalDAV erreur {resp.status_code} : {resp.text[:200]}")
            return False

    except Exception as e:
        print(f"   ❌ Erreur calendrier : {e}")
        return False


# ────────────────────────────────────────────────
# POINT D'ENTRÉE : depuis reponses.py
# ────────────────────────────────────────────────

def planifier_entretien(
    entreprise: str,
    poste: str,
    texte_email: str,
    date_forcee: datetime = None,
) -> bool:
    """
    Appelé quand un email recruteur est détecté comme entretien.
    Extrait la date, crée l'événement et notifie Telegram.
    """
    dt = date_forcee or extraire_datetime(texte_email)

    if not dt:
        # Pas de date trouvée → crée un événement placeholder dans 7 jours
        dt = datetime.now().replace(hour=10, minute=0, second=0) + timedelta(days=7)
        titre = f"🎯 Entretien à confirmer — {entreprise}"
        description = (
            f"Poste : {poste}\n"
            f"Date à confirmer avec le recruteur.\n\n"
            f"Extrait email :\n{texte_email[:300]}"
        )
        _telegram(
            f"📅 <b>Entretien ajouté au calendrier</b>\n\n"
            f"🏢 {entreprise} — {poste}\n"
            f"⚠️ Date non détectée — événement placeholder créé pour dans 7 jours\n"
            f"Pense à confirmer la date avec le recruteur !"
        )
    else:
        titre = f"🎯 Entretien {entreprise} — {poste}"
        description = (
            f"Poste : {poste}\n"
            f"Entreprise : {entreprise}\n\n"
            f"Extrait email :\n{texte_email[:300]}"
        )
        _telegram(
            f"📅 <b>Entretien ajouté à ton calendrier !</b>\n\n"
            f"🏢 <b>{entreprise}</b> — {poste}\n"
            f"🕐 <b>{dt.strftime('%A %d %B %Y à %Hh%M')}</b>\n\n"
            f"Rappels automatiques : 24h avant et 1h avant ⏰"
        )

    ok = ajouter_evenement_calendrier(titre, dt, description, duree_min=60)
    return ok


# ────────────────────────────────────────────────
# TEST
# ────────────────────────────────────────────────

if __name__ == "__main__":
    # Test parsing de date
    exemples = [
        "Nous souhaitons vous rencontrer le 15 avril 2026 à 14h00",
        "Disponible le mercredi 22 avril à 10h30 ?",
        "Entretien prévu le 20/04/2026 à 9h",
    ]
    for t in exemples:
        dt = extraire_datetime(t)
        print(f"'{t}' → {dt}")

    # Test ajout calendrier (décommente pour tester)
    # from datetime import datetime
    # ok = ajouter_evenement_calendrier(
    #     titre="Test entretien — Bot alternance",
    #     debut=datetime(2026, 4, 15, 14, 0),
    #     description="Test depuis l'agent IA",
    # )
    # print("Ajouté !" if ok else "Échec.")
