"""
scraper_hellowork.py — Scraper HelloWork (HTML)
Cherche les offres d'alternance data/IA sur HelloWork et les sauvegarde en base.

Usage:
    python scraper_hellowork.py
"""

import time
import re
import requests
from bs4 import BeautifulSoup
from memory import Memory

# ────────────────────────────────────────────────
# CONFIGURATION
# ────────────────────────────────────────────────

BASE_URL = "https://www.hellowork.com/fr-fr/emploi/recherche.html"

MOTS_CLES = [
    "Data Analyst",
    "Data Scientist",
    "Data Engineer",
    "Machine Learning",
    "AI Developer",
    "Développeur IA",
    "MLOps",
    "Développeur Full Stack",
    "Business Intelligence",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.hellowork.com/",
}

PAUSE       = 3    # secondes entre requêtes
PAGES_MAX   = 3    # pages par mot-clé


# ────────────────────────────────────────────────
# FONCTIONS
# ────────────────────────────────────────────────

def fetch_page(keyword: str, page: int = 1) -> str | None:
    """Récupère une page de résultats HelloWork."""
    params = {
        "k": keyword,
        "c": "Alternance",          # filtre contrat alternance
        "l": "France",
        "p": page,
    }
    try:
        resp = requests.get(BASE_URL, headers=HEADERS, params=params, timeout=15)
        if resp.status_code == 200:
            return resp.text
        print(f"   ⚠️  HelloWork status {resp.status_code} pour '{keyword}' (page {page})")
        return None
    except requests.RequestException as e:
        print(f"   ❌ Erreur réseau HelloWork : {e}")
        return None


def parser_offres(html: str) -> list[dict]:
    """Parse le HTML HelloWork et extrait les offres."""
    soup = BeautifulSoup(html, "html.parser")
    offres = []

    # HelloWork v2 : cartes = li[data-id-storage-item-id], données dans inputs cachés
    cards = soup.find_all("li", attrs={"data-id-storage-item-id": True})

    for card in cards:
        try:
            job_id = card.get("data-id-storage-item-id", "")
            if not job_id:
                continue

            url = f"https://www.hellowork.com/fr-fr/emplois/{job_id}.html"

            # Titre et entreprise via les inputs cachés du formulaire
            titre_inp = card.find("input", attrs={"name": "title"})
            company_inp = card.find("input", attrs={"name": "company"})
            titre = titre_inp.get("value", "") if titre_inp else ""
            entreprise = company_inp.get("value", "") if company_inp else ""

            if not titre:
                continue

            # Localisation : premier lien ou texte contenant le département
            # La structure est : "Ville - 75Alternance..." — on nettoie
            texte = card.get_text(separator=" | ", strip=True)
            localisation = ""
            for part in texte.split("|"):
                part = part.strip()
                if re.search(r"\d{2}$|\d{5}|Paris|Lyon|Bordeaux|Nantes|Rennes|Lille|Marseille|Toulouse|Strasbourg", part):
                    # Nettoie le numéro de département collé au nom de la ville
                    localisation = re.sub(r"\s*-\s*\d{2,5}$", "", part).strip()
                    if len(localisation) < 100:
                        break

            offres.append({
                "source":           "hellowork",
                "url":              url,
                "titre":            titre,
                "entreprise":       entreprise,
                "localisation":     localisation or "France",
                "description":      "",
                "date_publication": "",
                "score_pertinence": 0.0,
            })

        except Exception:
            continue

    return offres


def scraper_hellowork() -> int:
    """
    Lance le scraping HelloWork sur tous les mots-clés.
    Retourne le nombre de nouvelles offres ajoutées.
    """
    mem = Memory()
    total_nouvelles = 0

    for mot_cle in MOTS_CLES:
        print(f"\n🔍 HelloWork : '{mot_cle}'...")

        for page in range(1, PAGES_MAX + 1):
            html = fetch_page(mot_cle, page)
            if not html:
                break

            offres = parser_offres(html)
            if not offres:
                print(f"   📄 Page {page} — 0 offres (fin)")
                break

            nouvelles = 0
            for offre in offres:
                if mem.offre_existe(offre["url"]):
                    continue
                oid = mem.add_offre(offre)
                if oid:
                    nouvelles += 1
                    total_nouvelles += 1
                    print(f"   ➕ {offre['titre']} — {offre['entreprise']}")

            print(f"   📄 Page {page} — {nouvelles} nouvelles / {len(offres)} offres")

            if len(offres) < 10:
                break

            time.sleep(PAUSE)

        time.sleep(PAUSE)

    print(f"\n✅ HelloWork terminé — {total_nouvelles} nouvelles offres ajoutées.")
    return total_nouvelles


# ────────────────────────────────────────────────
# LANCEMENT
# ────────────────────────────────────────────────

if __name__ == "__main__":
    scraper_hellowork()
