"""
bot.py — Assistant conversationnel Telegram alimenté par Claude
Tu peux discuter des offres, demander des emails, voir les stats, etc.

Usage:
    python bot.py
"""

import asyncio
import io
import json
import os
import re
from pathlib import Path

import anthropic
import pypdf
import base64
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from memory import Memory

# ────────────────────────────────────────────────
# CONFIGURATION
# ────────────────────────────────────────────────

TELEGRAM_TOKEN   = "8658482373:AAH3Oxk6of_JWCVXRBXn_L4X9cIaHHMcDrc"
TELEGRAM_CHAT_ID = 7026975488
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
PROFIL_PATH = Path(__file__).parent / "profil_ali.json"

# Mémoire persistante
_mem = Memory()
conversation_history: list[dict] = _mem.load_history()


# ────────────────────────────────────────────────
# CONTEXTE POUR CLAUDE
# ────────────────────────────────────────────────

def charger_contexte() -> str:
    """Construit le contexte complet : profil + stats DB + mémoire personnalisée."""
    with open(PROFIL_PATH, "r", encoding="utf-8") as f:
        profil = json.load(f)

    mem = Memory()
    stats = mem.get_stats()
    souvenirs = mem.recall_all()

    # Top offres intéressantes
    with mem._connect() as conn:
        top_offres = conn.execute("""
            SELECT titre, entreprise, localisation, score_pertinence, notes, url, id
            FROM offres
            WHERE statut = 'intéressant'
            ORDER BY score_pertinence DESC
            LIMIT 20
        """).fetchall()

    top_str = "\n".join(
        f"  - [{o['id']}] {o['titre']} chez {o['entreprise']} ({o['localisation']}) — score {int(o['score_pertinence']*100)}% — {o['notes'] or ''}"
        for o in top_offres
    )

    r = profil["recherche_alternance"]
    id_info = profil["identite"]

    souvenirs_str = "\n".join(f"  - {k} : {v}" for k, v in souvenirs.items()) if souvenirs else "  (aucun souvenir pour l'instant)"

    return f"""Tu es l'assistant IA personnel d'Ali Benaqa, qui l'aide dans sa recherche d'alternance.
Tu es intégré dans Telegram et tu lui parles directement, comme un ami proche très compétent.
Tu es proactif, direct, bienveillant. Tu tutoies Ali.

=== PROFIL D'ALI ===
Nom : {id_info['nom_complet']}
Formation : Bachelor Data & IA — Hetic (3e année)
Disponibilité : {r['disponibilite']} | Durée : {r['duree_contrat']}
Postes ciblés : {', '.join(r['poste_cible'])}
Secteurs préférés : {', '.join(r['secteurs_preferes'])}
Localisation : {', '.join(r['localisation'])}
Expériences : Data Analyst (Techwin Services, BNC Corporation), Stage Reporting Analyst (Mamda Assurance)
Compétences : Python, SQL, Power BI, ETL, API REST, Excel, Machine Learning, Claude API

=== STATISTIQUES ACTUELLES ===
Offres scrappées : {stats['total_offres']}
Offres intéressantes : {stats['offres_par_statut'].get('intéressant', 0)}
Offres ignorées : {stats['offres_par_statut'].get('ignoré', 0)}
Candidatures envoyées : {stats['total_candidatures']}
Entretiens : {stats['entretiens']}
Taux de réponse : {stats['taux_reponse']}%

=== TOP OFFRES INTÉRESSANTES (avec leur ID entre crochets) ===
{top_str if top_str else "Aucune offre scorée pour l'instant."}

=== CE QU'ALI T'A DIT DE RETENIR ===
{souvenirs_str}

=== INSTRUCTIONS ===
- Réponds en français, COURT et DIRECT. Pas d'intro, pas de conclusion, pas de formules de politesse.
- Max 2-3 lignes sauf si on te demande explicitement un email ou une analyse détaillée.
- Pas de "Bien sûr !", "Avec plaisir !", "Voilà !", "Absolument !" — va direct à l'info.
- Si Ali demande les offres → liste immédiatement, rien d'autre.
- Si Ali demande un email → donne l'email directement, sans commentaire avant/après.
- Si Ali pose une question → réponds en 1-2 phrases max.
- IMPORTANT : si Ali te dit "retiens que...", "souviens-toi que...", "note que...", mémorise avec [RETENIR: cle=valeur] à la fin.
"""


# ────────────────────────────────────────────────
# APPEL CLAUDE
# ────────────────────────────────────────────────

def demander_claude_avec_image(message_user: str, image_bytes: bytes, mime_type: str) -> str:
    """Envoie un message + image à Claude (multimodal) et retourne la réponse."""
    if not ANTHROPIC_API_KEY:
        return "❌ Clé API Anthropic manquante."

    import base64
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    mem = Memory()

    mem.save_message("user", f"[Image envoyée] {message_user}")
    conversation_history.append({"role": "user", "content": f"[Image envoyée] {message_user}"})

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",  # Modèle vision
            max_tokens=1500,
            system=charger_contexte(),
            messages=[
                # Historique texte uniquement
                *conversation_history[-10:][:-1],
                # Dernier message avec image
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": base64.standard_b64encode(image_bytes).decode("utf-8"),
                            },
                        },
                        {"type": "text", "text": message_user or "Analyse cette image."},
                    ],
                }
            ],
        )
        reply = response.content[0].text.strip()

        souvenirs = re.findall(r'\[RETENIR:\s*([^=\]]+)=([^\]]+)\]', reply)
        for cle, valeur in souvenirs:
            mem.remember(cle.strip(), valeur.strip())
        reply_affiche = re.sub(r'\[RETENIR:[^\]]+\]', '', reply).strip()

        mem.save_message("assistant", reply_affiche)
        conversation_history.append({"role": "assistant", "content": reply_affiche})

        return reply_affiche

    except anthropic.APIError as e:
        return f"❌ Erreur API : {e}"


def demander_claude(message_user: str) -> str:
    """Envoie le message à Claude avec l'historique et retourne la réponse."""
    if not ANTHROPIC_API_KEY:
        return "❌ Clé API Anthropic manquante. Lance : export ANTHROPIC_API_KEY='sk-ant-...'"

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    mem = Memory()

    # Sauvegarde et ajoute le message de l'utilisateur
    mem.save_message("user", message_user)
    conversation_history.append({"role": "user", "content": message_user})

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=charger_contexte(),
            messages=conversation_history[-20:],
        )
        reply = response.content[0].text.strip()

        # Détecte si Claude veut mémoriser quelque chose
        import re
        souvenirs = re.findall(r'\[RETENIR:\s*([^=\]]+)=([^\]]+)\]', reply)
        for cle, valeur in souvenirs:
            mem.remember(cle.strip(), valeur.strip())
        # Nettoie les balises [RETENIR:...] du message affiché
        reply_affiche = re.sub(r'\[RETENIR:[^\]]+\]', '', reply).strip()

        # Sauvegarde la réponse
        mem.save_message("assistant", reply_affiche)
        conversation_history.append({"role": "assistant", "content": reply_affiche})

        return reply_affiche

    except anthropic.APIError as e:
        return f"❌ Erreur API : {e}"


# ────────────────────────────────────────────────
# HANDLERS TELEGRAM
# ────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /start"""
    if update.effective_user.id != TELEGRAM_CHAT_ID:
        return  # Ignore les inconnus

    conversation_history.clear()
    texte = demander_claude(
        "Ali vient de démarrer le bot. Présente-toi brièvement et donne-lui un résumé "
        "de l'état actuel de sa recherche d'alternance avec les stats clés."
    )
    await update.message.reply_text(texte)


async def cmd_offres(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /offres — affiche les meilleures offres avec boutons"""
    if update.effective_user.id != TELEGRAM_CHAT_ID:
        return

    mem = Memory()
    with mem._connect() as conn:
        offres = conn.execute("""
            SELECT id, titre, entreprise, localisation, score_pertinence, url
            FROM offres WHERE statut = 'intéressant'
            ORDER BY score_pertinence DESC LIMIT 10
        """).fetchall()

    if not offres:
        await update.message.reply_text("Aucune offre intéressante pour l'instant. Lance le scorer !")
        return

    await update.message.reply_text("🏆 <b>Tes 10 meilleures offres :</b>", parse_mode="HTML")

    for o in offres:
        score_pct = int(o["score_pertinence"] * 100)
        emoji = "🔥" if score_pct >= 90 else "✅" if score_pct >= 80 else "👍"
        texte = (
            f"{emoji} <b>{o['titre']}</b>\n"
            f"🏢 {o['entreprise']} — 📍 {o['localisation']}\n"
            f"⭐ {score_pct}%"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Intéressé", callback_data=f"interesse_{o['id']}"),
                InlineKeyboardButton("❌ Ignorer", callback_data=f"ignorer_{o['id']}"),
            ],
            [InlineKeyboardButton("📧 Rédiger email", callback_data=f"email_{o['id']}")],
        ])
        await update.message.reply_text(texte, parse_mode="HTML", reply_markup=keyboard)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /stats"""
    if update.effective_user.id != TELEGRAM_CHAT_ID:
        return

    texte = demander_claude("Donne-moi un résumé détaillé des statistiques de ma recherche d'alternance.")
    await update.message.reply_text(texte)


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /reset — remet la conversation à zéro"""
    if update.effective_user.id != TELEGRAM_CHAT_ID:
        return

    conversation_history.clear()
    Memory().clear_history()
    await update.message.reply_text("🔄 Conversation remise à zéro. Bonjour Ali !")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère tous les messages texte libres."""
    if update.effective_user.id != TELEGRAM_CHAT_ID:
        return

    user_text = update.message.text

    # Indicateur de frappe
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    reply = demander_claude(user_text)
    await update.message.reply_text(reply, parse_mode="HTML")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère les clics sur les boutons inline."""
    query = update.callback_query
    await query.answer()

    data = query.data
    mem = Memory()

    if data.startswith("interesse_"):
        offre_id = int(data.split("_")[1])
        mem.update_offre_statut(offre_id, "intéressant", "Ali a confirmé son intérêt")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("✅ Offre marquée comme prioritaire ! Tu veux que je rédige l'email de candidature ?")

    elif data.startswith("ignorer_"):
        offre_id = int(data.split("_")[1])
        mem.update_offre_statut(offre_id, "ignoré")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("⏭️ Offre ignorée.")

    elif data.startswith("email_"):
        offre_id = int(data.split("_")[1])
        with mem._connect() as conn:
            offre = conn.execute("SELECT * FROM offres WHERE id = ?", (offre_id,)).fetchone()

        if offre:
            await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")
            prompt = (
                f"Rédige un email de candidature pour cette offre d'alternance :\n"
                f"Poste : {offre['titre']}\n"
                f"Entreprise : {offre['entreprise']}\n"
                f"Localisation : {offre['localisation']}\n"
                f"Description : {offre['description'][:500] if offre['description'] else 'Non disponible'}\n\n"
                f"Utilise mon style : professionnel mais accessible, 150-200 mots, mets en avant mes 3 expériences data et ma formation Hetic."
            )
            email = demander_claude(prompt)
            await query.message.reply_text(f"📧 <b>Email de candidature :</b>\n\n{email}", parse_mode="HTML")


# ────────────────────────────────────────────────
# HANDLERS FICHIERS ET IMAGES
# ────────────────────────────────────────────────

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère les photos et screenshots envoyés par Ali."""
    if update.effective_user.id != TELEGRAM_CHAT_ID:
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # Récupère la photo en meilleure qualité
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    image_bytes = await file.download_as_bytearray()

    # Légende optionnelle comme instruction
    caption = update.message.caption or "Analyse cette image et dis-moi ce que tu vois. Si c'est une offre d'emploi, dis-moi si elle correspond à mon profil."

    reply = demander_claude_avec_image(caption, bytes(image_bytes), "image/jpeg")
    await update.message.reply_text(reply, parse_mode="HTML")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère les fichiers envoyés (PDF, images en fichier, etc.)."""
    if update.effective_user.id != TELEGRAM_CHAT_ID:
        return

    doc = update.message.document
    mime = doc.mime_type or ""
    caption = update.message.caption or ""

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    file = await context.bot.get_file(doc.file_id)
    file_bytes = await file.download_as_bytearray()

    # — PDF : extraction texte —
    if mime == "application/pdf" or doc.file_name.endswith(".pdf"):
        try:
            reader = pypdf.PdfReader(io.BytesIO(bytes(file_bytes)))
            texte = "\n".join(page.extract_text() or "" for page in reader.pages)
            if not texte.strip():
                await update.message.reply_text("⚠️ Je n'arrive pas à extraire le texte de ce PDF.")
                return

            texte_tronque = texte[:4000]
            instruction = caption or "Analyse ce document. Si c'est un CV, donne-moi des conseils d'amélioration. Si c'est une offre d'emploi, dis-moi si elle correspond à mon profil."
            prompt = f"{instruction}\n\n--- CONTENU DU PDF ---\n{texte_tronque}"
            reply = demander_claude(prompt)

        except Exception as e:
            reply = f"❌ Erreur lecture PDF : {e}"

    # — Image envoyée comme fichier —
    elif mime.startswith("image/"):
        instruction = caption or "Analyse cette image."
        reply = demander_claude_avec_image(instruction, bytes(file_bytes), mime)

    else:
        reply = f"⚠️ Format non supporté ({mime}). Envoie-moi un PDF ou une image."

    await update.message.reply_text(reply, parse_mode="HTML")


# ────────────────────────────────────────────────
# LANCEMENT
# ────────────────────────────────────────────────

def main():
    if not ANTHROPIC_API_KEY:
        print("❌ ANTHROPIC_API_KEY manquante. Lance : export ANTHROPIC_API_KEY='sk-ant-...'")
        return

    print("🤖 Bot Telegram démarré — en attente de messages...")
    print("   Commandes disponibles : /start /offres /stats /reset")
    print("   Ctrl+C pour arrêter\n")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("offres", cmd_offres))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
