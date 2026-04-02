"""
alumni_linkedin.py — Trouve les alumni Hetic sur LinkedIn via DuckDuckGo
et leur envoie un email de networking pour demander de l'aide alternance.

Stratégie :
1. DuckDuckGo → profiles LinkedIn "Hetic" + postes data/tech
2. Hunter.io → email pro basé sur leur entreprise actuelle
3. Claude → email personnalisé chaleureux (pas un template générique)
4. Gmail API → envoi + notification Telegram
"""

import os
import re
import time
import json
import requests
from bs4 import BeautifulSoup
from pathlib import Path

import anthropic

from memory import Memory
from hunter import trouver_email_recruteur
from emailer import envoyer_email

TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "8658482373:AAH3Oxk6of_JWCVXRBXn_L4X9cIaHHMcDrc")
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "7026975488")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CV_PATH           = Path(__file__).parent / "cv_ali.pdf"

MAX_ALUMNI_PAR_CYCLE = 5   # emails envoyés par cycle, évite le spam
PAUSE               = 4    # secondes entre requêtes DDG

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Postes pertinents pour filtrer les alumni (seulement tech/data)
POSTES_PERTINENTS = [
    "data analyst", "data scientist", "data engineer", "machine learning",
    "ml engineer", "ai engineer", "ai developer", "développeur", "developer",
    "fullstack", "full stack", "full-stack", "business intelligence",
    "bi analyst", "mlops", "ingénieur données", "ingénieur data",
    "software engineer", "backend", "frontend", "tech lead",
]

# Requêtes DDG pour trouver des alumni Hetic dans la tech/data
DDG_QUERIES = [
    'site:linkedin.com/in "Hetic" "Data Analyst" Paris',
    'site:linkedin.com/in "Hetic" "Data Scientist"',
    'site:linkedin.com/in "Hetic" "Data Engineer"',
    'site:linkedin.com/in "Hetic" "Développeur" Paris',
    'site:linkedin.com/in "école Hetic" "Engineer"',
    'site:linkedin.com/in "Hetic" "Machine Learning"',
]


# ────────────────────────────────────────────────
# UTILITAIRES
# ────────────────────────────────────────────────

def _telegram(texte: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": texte, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass


def poste_est_pertinent(poste: str) -> bool:
    """Retourne True si le poste de l'alumni est dans un domaine tech/data."""
    poste_lower = poste.lower()
    return any(mot in poste_lower for mot in POSTES_PERTINENTS)


# ────────────────────────────────────────────────
# SCRAPING DUCKDUCKGO → LINKEDIN PROFILES
# ────────────────────────────────────────────────

def _ddg_search(query: str) -> list[dict]:
    """Recherche DuckDuckGo HTML et retourne les résultats LinkedIn trouvés."""
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query, "kl": "fr-fr"},
            headers=HEADERS,
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"   ⚠️  DDG status {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        resultats = []

        for result in soup.find_all("div", class_="result__body"):
            lien_el  = result.find("a", class_="result__a")
            snip_el  = result.find("a", class_="result__snippet")
            if not lien_el:
                continue

            href = lien_el.get("href", "")
            # DDG encode parfois l'URL dans un paramètre uddg
            if "uddg=" in href:
                from urllib.parse import unquote, parse_qs, urlparse
                qs = parse_qs(urlparse(href).query)
                href = unquote(qs.get("uddg", [""])[0])

            if "linkedin.com/in/" not in href:
                continue

            # Nettoie l'URL LinkedIn (enlève tracking)
            url_clean = href.split("?")[0].rstrip("/")

            resultats.append({
                "linkedin_url": url_clean,
                "titre":   lien_el.get_text(strip=True),
                "snippet": snip_el.get_text(strip=True) if snip_el else "",
            })

        return resultats

    except Exception as e:
        print(f"   ❌ DDG erreur : {e}")
        return []


def _parser_titre_linkedin(titre: str, snippet: str) -> dict:
    """
    Extrait prénom, nom, poste, entreprise depuis un titre LinkedIn.
    Exemples de titres :
      "Sarah Martin - Data Analyst chez BNP Paribas | LinkedIn"
      "Ali Ben - Software Engineer at Doctolib | LinkedIn"
      "Tom D. · Data Scientist | Hetic Alumni"
    """
    alumnus = {
        "prenom": "", "nom": "",
        "poste_actuel": "", "entreprise": "",
        "promotion": "Hetic",
    }

    titre_clean = re.sub(r"\s*[\|·]\s*LinkedIn.*$", "", titre, flags=re.IGNORECASE).strip()
    titre_clean = re.sub(r"\s*[\|·]\s*Hetic.*$", "", titre_clean, flags=re.IGNORECASE).strip()

    if " - " in titre_clean:
        parties = titre_clean.split(" - ", 1)
        nom_complet = parties[0].strip()
        poste_entreprise = parties[1].strip()
    else:
        # Parfois : "Prénom NOM · Poste chez Entreprise"
        titre_clean2 = titre_clean.replace(" · ", " - ", 1)
        if " - " in titre_clean2:
            parties = titre_clean2.split(" - ", 1)
            nom_complet = parties[0].strip()
            poste_entreprise = parties[1].strip()
        else:
            nom_complet = titre_clean
            poste_entreprise = snippet

    # Prénom / Nom
    mots = nom_complet.split()
    if mots:
        alumnus["prenom"] = mots[0]
        alumnus["nom"] = " ".join(mots[1:]) if len(mots) > 1 else ""

    # Poste et Entreprise : "Poste chez Entreprise" ou "Poste at Company"
    for sep in [" chez ", " at ", " @ ", " - "]:
        if sep in poste_entreprise.lower():
            idx = poste_entreprise.lower().find(sep)
            alumnus["poste_actuel"] = poste_entreprise[:idx].strip()
            alumnus["entreprise"]   = poste_entreprise[idx + len(sep):].strip()
            # Nettoie l'entreprise (enlève suffixes inutiles)
            alumnus["entreprise"] = re.sub(
                r"\s*([\|·,;].*|Inc\.?|SAS|SA|SARL|France)$", "",
                alumnus["entreprise"], flags=re.IGNORECASE
            ).strip()
            break

    if not alumnus["poste_actuel"]:
        alumnus["poste_actuel"] = poste_entreprise.strip()

    return alumnus


def scraper_alumni_hetic() -> list[dict]:
    """
    Lance les recherches DDG et retourne les alumni Hetic trouvés (nouveaux seulement).
    Filtre sur les postes tech/data pertinents.
    """
    mem = Memory()
    tous_alumni = []
    urls_vus = set()

    for query in DDG_QUERIES:
        print(f"   🔍 '{query}'")
        resultats = _ddg_search(query)
        print(f"      → {len(resultats)} profil(s) LinkedIn trouvés")

        for r in resultats:
            url = r["linkedin_url"]
            if url in urls_vus:
                continue
            urls_vus.add(url)

            # Déjà en base ?
            with mem._connect() as conn:
                existe = conn.execute(
                    "SELECT 1 FROM alumni WHERE linkedin_url = ?", (url,)
                ).fetchone()
            if existe:
                continue

            alumnus = _parser_titre_linkedin(r["titre"], r["snippet"])
            alumnus["linkedin_url"] = url

            if not alumnus["prenom"]:
                continue  # pas assez d'info

            # Filtre poste
            if alumnus["poste_actuel"] and not poste_est_pertinent(alumnus["poste_actuel"]):
                continue

            tous_alumni.append(alumnus)
            print(
                f"   ✅ {alumnus['prenom']} {alumnus['nom']} — "
                f"{alumnus['poste_actuel']} @ {alumnus['entreprise']}"
            )

        time.sleep(PAUSE)

    return tous_alumni


# ────────────────────────────────────────────────
# RECHERCHE EMAIL VIA HUNTER
# ────────────────────────────────────────────────

def _trouver_email_alumni(alumnus: dict) -> str | None:
    """
    Cherche l'email pro de l'alumni via Hunter.io.
    Essaye de construire l'email personnalisé prenom.nom@domaine.
    """
    entreprise = alumnus.get("entreprise", "").strip()
    if not entreprise:
        return None

    contact = trouver_email_recruteur(entreprise)
    if not contact or not contact.get("domaine"):
        return None

    domaine = contact["domaine"]
    prenom  = alumnus.get("prenom", "").lower().strip()
    nom     = alumnus.get("nom", "").lower().strip()

    # Caractères spéciaux (accents)
    def normalise(s: str) -> str:
        import unicodedata
        return "".join(
            c for c in unicodedata.normalize("NFD", s)
            if unicodedata.category(c) != "Mn"
        )

    prenom_n = normalise(prenom)
    nom_n    = normalise(nom).replace(" ", "").replace("-", "")

    if prenom_n and nom_n:
        return f"{prenom_n}.{nom_n}@{domaine}"  # pattern le plus courant
    elif prenom_n:
        return contact.get("email")  # email générique du domaine
    return None


# ────────────────────────────────────────────────
# GÉNÉRATION EMAIL NETWORKING VIA CLAUDE
# ────────────────────────────────────────────────

def generer_email_alumni(alumnus: dict) -> dict:
    """Génère un email de networking chaleureux et personnalisé via Claude."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prenom    = alumnus.get("prenom", "")
    poste     = alumnus.get("poste_actuel", "")
    entreprise = alumnus.get("entreprise", "ton entreprise")

    prompt = f"""Rédige un email de networking authentique et percutant de la part d'Ali Benaqa.

CONTEXTE :
Ali est étudiant en 2e année de Bachelor Data & IA à Hetic (Grande École de la Tech, Montreuil).
Il contacte un alumni Hetic pour demander de l'aide dans sa recherche d'alternance.
Il sera en 3e année (Bac+3) à partir de septembre 2026.

PROFIL ALI (à mentionner de façon naturelle, pas en liste) :
- 2e année Bachelor Data & IA, Hetic Montreuil — 3e année dès septembre 2026
- 3 expériences : Data Analyst freelance Techwin Services (ETL Python, pipelines de données),
  Reporting Analyst stage Mamda Assurance Maroc (Power BI, PHP/MySQL, reporting automatisé),
  Data Analyst BNC Corporation Maroc (KPI commerciaux, tableaux de bord EViews/Excel)
- Stack : Python, SQL, Power BI, ETL, JavaScript, Node.js, React, PHP, MySQL, MongoDB, Git
- Projet phare : agent IA autonome en Python qui scrape des offres d'alternance, les score avec Claude API et postule automatiquement — déployé sur Railway, piloté via Telegram
- GitHub : https://github.com/Alibenaqa | Paris (75011)

ALUMNI CONTACTÉ :
- Prénom : {prenom}
- Poste actuel : {poste or "non précisé"}
- Entreprise : {entreprise}

INSTRUCTIONS :
- Commence par "Bonjour {prenom}," (jamais Madame/Monsieur)
- Mentionne Hetic comme point commun dès la 1re phrase ("fellow Héticien" ou similaire)
- Dis que tu as vu son parcours chez {entreprise} (adapte le compliment au domaine)
- Explique en 1-2 phrases ta situation et ce que tu cherches (alternance oct 2026)
- Mentionne l'agent IA que tu as développé — ça montre ton niveau d'initiative
- Demande clairement : est-ce que {entreprise} recrute des alternants data/IA ?
  Et si oui, pourrait-il transmettre ton CV en interne ?
- Propose aussi un échange rapide de 15 min si ça l'intéresse
- Joint en pièce jointe : CV Ali Benaqa (mentionne-le dans le texte)
- Ton : chaleureux, direct, pas trop formel — 160-200 mots MAX
- Pas de "j'espère que vous allez bien", pas de langue de bois
- Signature : "Ali Benaqa | Hetic Bachelor Data & IA | +33 6 67 67 79 37 | alibenaqa123@gmail.com"
- Réponds avec ce format exact :

OBJET: [sujet court et accrocheur, max 60 caractères]
---
[corps de l'email]"""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        texte = resp.content[0].text.strip()

        objet = f"Alumni Hetic — alternance Data/IA — Ali Benaqa"
        corps = texte

        if "OBJET:" in texte and "---" in texte:
            parties = texte.split("---", 1)
            objet = parties[0].replace("OBJET:", "").strip()
            corps = parties[1].strip()

        return {"objet": objet, "corps": corps}

    except Exception as e:
        print(f"   ❌ Erreur génération email alumni : {e}")
        return {
            "objet": f"Alumni Hetic — alternance Data/IA — Ali Benaqa",
            "corps": (
                f"Bonjour {prenom},\n\n"
                f"Je suis Ali Benaqa, étudiant en Bachelor Data & IA à Hetic. "
                f"En tant que fellow Héticien, je me permets de te contacter.\n\n"
                f"Je cherche une alternance à partir d'octobre 2026 (Bac+3) et j'ai vu ton parcours chez {entreprise}. "
                f"Est-ce que {entreprise} recrute des alternants data/IA ? Si oui, pourrais-tu transmettre mon CV en interne ?\n\n"
                f"Mon CV est en pièce jointe. Merci d'avance !\n\n"
                f"Ali Benaqa | Hetic Bachelor Data & IA | +33 6 67 67 79 37 | alibenaqa123@gmail.com"
            ),
        }


# ────────────────────────────────────────────────
# CYCLE PRINCIPAL
# ────────────────────────────────────────────────

def run_alumni_outreach() -> dict:
    """
    Cycle complet alumni :
    1. Scrape nouveaux alumni Hetic sur LinkedIn via DDG
    2. Sauvegarde en base
    3. Pour chaque alumni non contacté : trouve email → génère mail → envoie → notif Telegram
    Retourne les stats du cycle.
    """
    print(f"\n🎓 Outreach Alumni Hetic — démarrage")
    mem = Memory()

    # ── 1. Scraping ──────────────────────────────────────────────
    print("\n[1/3] Scraping LinkedIn via DuckDuckGo...")
    nouveaux = scraper_alumni_hetic()

    nb_sauvegardes = 0
    for a in nouveaux:
        aid = mem.add_alumni(a)
        if aid:
            nb_sauvegardes += 1
    print(f"   ✅ {nb_sauvegardes} nouveaux alumni sauvegardés en base")

    # ── 2. Alumni à contacter (non contactés, avec ou sans email) ─
    print("\n[2/3] Sélection des alumni à contacter...")
    with mem._connect() as conn:
        rows = conn.execute("""
            SELECT * FROM alumni
            WHERE contacte = 0 AND entreprise IS NOT NULL AND entreprise != ''
            ORDER BY date_scrape DESC
        """).fetchall()
    alumni_liste = [dict(r) for r in rows][:MAX_ALUMNI_PAR_CYCLE]
    print(f"   → {len(alumni_liste)} alumni éligibles (max {MAX_ALUMNI_PAR_CYCLE}/cycle)")

    # ── 3. Envoi des emails ──────────────────────────────────────
    print("\n[3/3] Envoi des emails de networking...")
    stats = {"scrapes": nb_sauvegardes, "emails_envoyes": 0, "echecs_email": 0}

    for alumnus in alumni_liste:
        prenom    = alumnus.get("prenom", "?")
        entreprise = alumnus.get("entreprise", "?")
        print(f"\n➡️  {prenom} {alumnus.get('nom', '')} — {alumnus.get('poste_actuel', '')} @ {entreprise}")

        # Trouve l'email
        email_dest = alumnus.get("email") or _trouver_email_alumni(alumnus)
        if not email_dest:
            print(f"   ❌ Aucun email trouvé — skip")
            stats["echecs_email"] += 1
            # Marque quand même comme "tenté" pour ne pas re-boucler dessus indéfiniment
            with mem._connect() as conn:
                conn.execute(
                    "UPDATE alumni SET notes = 'email introuvable' WHERE id = ?",
                    (alumnus["id"],)
                )
            continue

        print(f"   📧 Email : {email_dest}")

        # Génère l'email
        email_data = generer_email_alumni(alumnus)

        # Envoie
        ok = envoyer_email(
            destinataire=email_dest,
            sujet=email_data["objet"],
            corps=email_data["corps"],
        )

        if ok:
            mem.marquer_alumni_contacte(alumnus["id"])
            with mem._connect() as conn:
                conn.execute(
                    "UPDATE alumni SET email = ?, statut_contact = 'mail envoyé' WHERE id = ?",
                    (email_dest, alumnus["id"])
                )
            stats["emails_envoyes"] += 1

            _telegram(
                f"🎓 <b>Alumni contacté !</b>\n\n"
                f"👤 <b>{prenom} {alumnus.get('nom', '')}</b>\n"
                f"💼 {alumnus.get('poste_actuel', '')} chez {entreprise}\n"
                f"📧 Mail envoyé à : <code>{email_dest}</code>\n\n"
                f"<b>Objet :</b> {email_data['objet']}\n\n"
                f"<b>Mail :</b>\n{email_data['corps'][:600]}\n\n"
                f"🤞 Croisons les doigts !"
            )
        else:
            stats["echecs_email"] += 1

        time.sleep(2)

    print(
        f"\n✅ Alumni outreach terminé — "
        f"{stats['emails_envoyes']} emails envoyés, "
        f"{stats['echecs_email']} échecs"
    )
    return stats


if __name__ == "__main__":
    stats = run_alumni_outreach()
    print(f"\n📊 Stats finales : {stats}")
