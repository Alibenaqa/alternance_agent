"""
notifier.py — Notifications Telegram des meilleures offres
Envoie les offres 'intéressant' pas encore notifiées sur le téléphone d'Ali.

Usage:
    python notifier.py
"""

import requests
from memory import Memory

# ────────────────────────────────────────────────
# CONFIGURATION
# ────────────────────────────────────────────────

TELEGRAM_TOKEN   = "8658482373:AAH3Oxk6of_JWCVXRBXn_L4X9cIaHHMcDrc"
TELEGRAM_CHAT_ID = "7026975488"
TELEGRAM_API     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

SCORE_EMOJI = {
    (0.9, 1.0): "🔥",
    (0.8, 0.9): "✅",
    (0.7, 0.8): "👍",
    (0.0, 0.7): "📌",
}


# ────────────────────────────────────────────────
# FONCTIONS
# ────────────────────────────────────────────────

def get_emoji(score: float) -> str:
    for (low, high), emoji in SCORE_EMOJI.items():
        if low <= score <= high:
            return emoji
    return "📌"


def envoyer_message(texte: str) -> bool:
    """Envoie un message Telegram. Retourne True si succès."""
    r = requests.post(
        f"{TELEGRAM_API}/sendMessage",
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": texte,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=10,
    )
    return r.ok


def formater_offre(offre: dict) -> str:
    """Formate une offre en message Telegram lisible."""
    emoji = get_emoji(offre["score_pertinence"])
    score_pct = int(offre["score_pertinence"] * 100)

    lignes = [
        f"{emoji} <b>{offre['titre']}</b>",
        f"🏢 {offre['entreprise']}",
        f"📍 {offre['localisation'] or 'Non précisé'}",
        f"⭐ Score : {score_pct}%",
    ]
    if offre.get("notes"):
        lignes.append(f"💬 {offre['notes']}")
    lignes.append(f"🔗 <a href=\"{offre['url']}\">Voir l'offre</a>")

    return "\n".join(lignes)


def notifier_offres() -> int:
    """
    Envoie les offres intéressantes pas encore notifiées.
    Retourne le nombre de notifications envoyées.
    """
    mem = Memory()
    offres = mem.get_offres_non_notifiees()

    if not offres:
        print("ℹ️  Aucune nouvelle offre à notifier.")
        return 0

    print(f"📲 Envoi de {len(offres)} notification(s) Telegram...\n")

    # Message d'intro groupé
    intro = (
        f"🤖 <b>Agent Alternance — {len(offres)} nouvelle(s) offre(s)</b>\n"
        f"Voici les meilleures offres trouvées pour toi :\n"
        f"{'─' * 30}"
    )
    envoyer_message(intro)

    envoyees = 0
    for offre in offres:
        message = formater_offre(offre)
        if envoyer_message(message):
            mem.marquer_notif_envoyee(offre["id"])
            envoyees += 1
            print(f"  ✅ Envoyé : {offre['titre']} — {offre['entreprise']}")
        else:
            print(f"  ❌ Échec : {offre['titre']}")

    # Message de fin
    envoyer_message(f"✅ <b>Fin du rapport</b> — {envoyees} offre(s) envoyée(s).")
    print(f"\n✅ {envoyees} notifications envoyées.")
    return envoyees


# ────────────────────────────────────────────────
# ALERTE IMMÉDIATE OFFRES TOP (>90%)
# ────────────────────────────────────────────────

def alerter_offres_top() -> int:
    """
    Envoie une alerte immédiate pour les offres scorées >90% pas encore notifiées.
    Appelé juste après le scoring, avant le cycle complet.
    """
    mem = Memory()
    with mem._connect() as conn:
        offres = conn.execute("""
            SELECT * FROM offres
            WHERE score_pertinence >= 0.90
              AND notif_envoyee = 0
              AND statut = 'intéressant'
            ORDER BY score_pertinence DESC
        """).fetchall()

    if not offres:
        return 0

    envoyer_message(
        f"🔥 <b>{len(offres)} offre(s) TOP à +90% trouvée(s) !</b>"
    )

    nb = 0
    for offre in offres:
        offre = dict(offre)
        message = (
            f"🔥🔥 <b>OFFRE TOP — {int(offre['score_pertinence'] * 100)}%</b>\n\n"
            + formater_offre(offre)
        )
        if envoyer_message(message):
            mem.marquer_notif_envoyee(offre["id"])
            nb += 1

    return nb


# ────────────────────────────────────────────────
# LANCEMENT
# ────────────────────────────────────────────────

if __name__ == "__main__":
    notifier_offres()
