"""
hunter.py — Trouve les emails RH d'une entreprise via Hunter.io API
"""

import os
import requests

HUNTER_API_KEY = os.environ.get("HUNTER_API_KEY", "25432bcf023d8760f920b39e8f4a3e96d8ef02cb")
BASE_URL = "https://api.hunter.io/v2"


def trouver_email_recruteur(entreprise: str, domaine: str = None) -> dict | None:
    """
    Cherche l'email RH/recrutement d'une entreprise.
    Retourne {"email": ..., "confiance": ..., "nom": ...} ou None.
    """
    # Étape 1 : trouver le domaine si pas fourni
    if not domaine:
        domaine = trouver_domaine(entreprise)
    if not domaine:
        return None

    # Étape 2 : chercher les emails du domaine
    try:
        resp = requests.get(
            f"{BASE_URL}/domain-search",
            params={
                "domain": domaine,
                "api_key": HUNTER_API_KEY,
                "limit": 10,
                "type": "personal",
            },
            timeout=10,
        )
        data = resp.json().get("data", {})
        emails = data.get("emails", [])

        if not emails:
            return None

        # Priorité : RH > recrutement > talent > tout autre
        mots_rh = ["rh", "hr", "recrutement", "recruitment", "talent", "people", "careers"]

        # Cherche un email RH en priorité
        for email_info in emails:
            prenom = (email_info.get("first_name") or "").lower()
            nom_dep = (email_info.get("department") or "").lower()
            position = (email_info.get("position") or "").lower()
            adresse = (email_info.get("value") or "").lower()

            if any(mot in nom_dep or mot in position or mot in adresse for mot in mots_rh):
                return {
                    "email": email_info["value"],
                    "nom": f"{email_info.get('first_name', '')} {email_info.get('last_name', '')}".strip(),
                    "confiance": email_info.get("confidence", 0),
                    "domaine": domaine,
                }

        # Sinon prend le premier email avec le plus de confiance
        meilleur = max(emails, key=lambda e: e.get("confidence", 0))
        return {
            "email": meilleur["value"],
            "nom": f"{meilleur.get('first_name', '')} {meilleur.get('last_name', '')}".strip(),
            "confiance": meilleur.get("confidence", 0),
            "domaine": domaine,
        }

    except Exception as e:
        print(f"   ❌ Hunter domain-search : {e}")
        return None


def trouver_domaine(entreprise: str) -> str | None:
    """Devine le domaine web d'une entreprise."""
    # Dictionnaire des entreprises fréquentes
    DOMAINES_CONNUS = {
        "capgemini": "capgemini.com",
        "sopra": "soprasteria.com",
        "sopra steria": "soprasteria.com",
        "accenture": "accenture.com",
        "thales": "thalesgroup.com",
        "bnp paribas": "bnpparibas.com",
        "bnpparibas": "bnpparibas.com",
        "société générale": "societegenerale.com",
        "axa": "axa.com",
        "allianz": "allianz.fr",
        "grdf": "grdf.fr",
        "edf": "edf.fr",
        "orange": "orange.com",
        "sncf": "sncf.com",
        "airbus": "airbus.com",
        "dassault": "dassault-systemes.com",
        "michelin": "michelin.com",
        "total": "totalenergies.com",
        "totalenergies": "totalenergies.com",
        "lvmh": "lvmh.com",
        "l'oréal": "loreal.com",
        "loreal": "loreal.com",
        "danone": "danone.com",
        "sanofi": "sanofi.com",
        "boursobank": "boursobank.com",
        "bforbank": "bforbank.com",
        "canal+": "canalplus.com",
        "canal plus": "canalplus.com",
        "chanel": "chanel.com",
        "hermes": "hermes.com",
        "hermès": "hermes.com",
        "lacoste": "lacoste.com",
        "dior": "dior.com",
        "christian dior": "dior.com",
        "volkswagen": "vwfs.fr",
        "samsung": "samsung.com",
        "servier": "servier.com",
        "bpce": "bpce.fr",
        "klesia": "klesia.fr",
        "sgeti": "sogeti.fr",
        "sogeti": "sogeti.fr",
        "upsa": "upsa.fr",
        "juridica": "juridica.fr",
        "affluences": "affluences.com",
        "aon": "aon.com",
    }

    nom = entreprise.lower().strip()
    for cle, domaine in DOMAINES_CONNUS.items():
        if cle in nom or nom in cle:
            return domaine

    # Fallback : construit un domaine probable
    nom_propre = entreprise.lower()
    for car in [" ", "'", "-", ".", ","]:
        nom_propre = nom_propre.replace(car, "")
    return f"{nom_propre}.com"


def verifier_email(email: str) -> bool:
    """Vérifie qu'un email est valide avant d'envoyer."""
    try:
        resp = requests.get(
            f"{BASE_URL}/email-verifier",
            params={"email": email, "api_key": HUNTER_API_KEY},
            timeout=10,
        )
        statut = resp.json().get("data", {}).get("status", "")
        return statut in ("valid", "accept_all")
    except Exception:
        return True  # en cas d'erreur, on tente quand même


if __name__ == "__main__":
    # Test rapide
    entreprises = ["BoursoBank", "Capgemini", "GRDF"]
    for e in entreprises:
        print(f"\n🔍 {e}...")
        result = trouver_email_recruteur(e)
        if result:
            print(f"   ✅ {result['email']} ({result['nom']}) — confiance {result['confiance']}%")
        else:
            print(f"   ❌ Aucun email trouvé")
