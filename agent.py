"""
agent.py — Orchestrateur principal de l'agent de recherche d'alternance
Lance automatiquement : scraping → scoring → notification Telegram

Usage:
    python agent.py          # un seul cycle
    python agent.py --loop   # tourne en boucle toutes les 12h
"""

import os
import sys
import time
from datetime import datetime

from scraper_wttj import scraper_wttj
from scraper_linkedin import scraper_linkedin
from scorer import scorer_offres_nouvelles
from notifier import notifier_offres
from memory import Memory


# ────────────────────────────────────────────────
# CONFIGURATION
# ────────────────────────────────────────────────

INTERVALLE_HEURES = 12  # relance automatique toutes les 12h en mode --loop


# ────────────────────────────────────────────────
# UTILITAIRES
# ────────────────────────────────────────────────

def log(msg: str):
    heure = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{heure}] {msg}")


def envoyer_telegram(texte: str):
    """Envoie un message direct via l'API Telegram (sans bot.py)."""
    import requests
    token = "8658482373:AAH3Oxk6of_JWCVXRBXn_L4X9cIaHHMcDrc"
    chat_id = "7026975488"
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": texte, "parse_mode": "HTML"},
        timeout=10,
    )


# ────────────────────────────────────────────────
# CYCLE PRINCIPAL
# ────────────────────────────────────────────────

def run_cycle():
    """Un cycle complet : scrape → score → notifie."""
    debut = datetime.now()
    log("=" * 50)
    log("🚀 Démarrage du cycle agent")
    log("=" * 50)

    envoyer_telegram("🤖 <b>Agent démarré</b> — cycle en cours...")

    # ── ÉTAPE 1 : SCRAPING ──────────────────────
    log("📡 Étape 1/3 — Scraping WTTJ + LinkedIn...")
    nb_nouvelles = 0
    try:
        nb_nouvelles += scraper_wttj()
        log(f"✅ WTTJ terminé")
    except Exception as e:
        log(f"❌ Erreur scraping WTTJ : {e}")
    try:
        nb_nouvelles += scraper_linkedin()
        log(f"✅ LinkedIn terminé")
    except Exception as e:
        log(f"❌ Erreur scraping LinkedIn : {e}")
    log(f"📡 Total nouvelles offres : {nb_nouvelles}")

    # ── ÉTAPE 2 : SCORING ───────────────────────
    log("🤖 Étape 2/3 — Scoring Claude...")
    try:
        stats_scoring = scorer_offres_nouvelles()
        log(f"✅ Scoring terminé — {stats_scoring['interessantes']} intéressantes, {stats_scoring['ignorees']} ignorées")
    except EnvironmentError as e:
        log(f"❌ {e}")
        stats_scoring = {"interessantes": 0, "ignorees": 0, "erreurs": 0}
    except Exception as e:
        log(f"❌ Erreur scoring : {e}")
        stats_scoring = {"interessantes": 0, "ignorees": 0, "erreurs": 0}

    # ── ÉTAPE 3 : NOTIFICATIONS ─────────────────
    log("📲 Étape 3/3 — Notifications Telegram...")
    try:
        nb_notifs = notifier_offres()
        log(f"✅ {nb_notifs} notifications envoyées")
    except Exception as e:
        log(f"❌ Erreur notifications : {e}")
        nb_notifs = 0

    # ── RÉSUMÉ ──────────────────────────────────
    duree = int((datetime.now() - debut).total_seconds())
    mem = Memory()
    stats = mem.get_stats()

    resume = (
        f"✅ <b>Cycle terminé</b> ({duree}s)\n"
        f"📡 Nouvelles offres : {nb_nouvelles}\n"
        f"✅ Intéressantes : {stats_scoring['interessantes']}\n"
        f"📲 Notifications : {nb_notifs}\n"
        f"📊 Total en base : {stats['total_offres']} offres | {stats['entretiens']} entretiens"
    )

    log(resume.replace("<b>", "").replace("</b>", ""))
    envoyer_telegram(resume)

    return {"nouvelles": nb_nouvelles, "interessantes": stats_scoring["interessantes"], "notifs": nb_notifs}


# ────────────────────────────────────────────────
# MODES DE LANCEMENT
# ────────────────────────────────────────────────

def mode_unique():
    """Lance un seul cycle puis s'arrête."""
    run_cycle()


def mode_boucle():
    """Tourne en boucle toutes les N heures."""
    log(f"🔄 Mode boucle activé — cycle toutes les {INTERVALLE_HEURES}h")
    envoyer_telegram(f"🔄 <b>Agent en mode automatique</b> — cycle toutes les {INTERVALLE_HEURES}h")

    while True:
        run_cycle()
        prochain = datetime.now().strftime("%H:%M")
        log(f"💤 Pause de {INTERVALLE_HEURES}h — prochain cycle dans {INTERVALLE_HEURES}h")
        envoyer_telegram(f"💤 Prochain cycle dans <b>{INTERVALLE_HEURES}h</b>")
        time.sleep(INTERVALLE_HEURES * 3600)


if __name__ == "__main__":
    # Vérifie la clé API
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("❌ ANTHROPIC_API_KEY manquante.")
        print("   Lance : export ANTHROPIC_API_KEY='sk-ant-...'")
        sys.exit(1)

    if "--loop" in sys.argv:
        mode_boucle()
    else:
        mode_unique()
