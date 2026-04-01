"""
dashboard.py — Dashboard web interactif pour l'agent alternance
Serveur Flask qui expose une API REST + page HTML auto-rafraîchissante.

Lancé dans un thread séparé depuis main.py.
Accessible sur l'URL Railway du projet.
"""

import os
import threading
from datetime import datetime
from flask import Flask, jsonify, render_template_string

from memory import Memory

app = Flask(__name__)
PORT = int(os.environ.get("PORT", 8080))


# ────────────────────────────────────────────────
# API ENDPOINTS
# ────────────────────────────────────────────────

@app.route("/api/stats")
def api_stats():
    mem = Memory()
    stats = mem.get_stats()
    with mem._connect() as conn:
        sources = conn.execute("""
            SELECT source, COUNT(*) as nb FROM offres GROUP BY source
        """).fetchall()
        cands_semaine = conn.execute("""
            SELECT COUNT(*) FROM candidatures
            WHERE date_candidature >= datetime('now', '-7 days')
        """).fetchone()[0]
        derniere_cand = conn.execute("""
            SELECT c.date_candidature, o.entreprise, o.titre
            FROM candidatures c LEFT JOIN offres o ON c.offre_id = o.id
            ORDER BY c.date_candidature DESC LIMIT 1
        """).fetchone()

    return jsonify({
        **stats,
        "sources": {r["source"]: r["nb"] for r in sources},
        "candidatures_semaine": cands_semaine,
        "derniere_candidature": dict(derniere_cand) if derniere_cand else None,
        "updated_at": datetime.now().strftime("%H:%M:%S"),
    })


@app.route("/api/candidatures")
def api_candidatures():
    mem = Memory()
    with mem._connect() as conn:
        rows = conn.execute("""
            SELECT c.id, c.canal, c.email_dest, c.statut, c.nb_relances,
                   c.date_candidature, o.titre, o.entreprise, o.localisation,
                   o.score_pertinence, o.statut as statut_offre, o.url
            FROM candidatures c
            LEFT JOIN offres o ON c.offre_id = o.id
            ORDER BY c.date_candidature DESC
            LIMIT 50
        """).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/offres")
def api_offres():
    mem = Memory()
    with mem._connect() as conn:
        rows = conn.execute("""
            SELECT id, titre, entreprise, localisation, source,
                   score_pertinence, statut, url, date_scrape
            FROM offres
            WHERE statut IN ('intéressant', 'postulé', 'entretien')
            ORDER BY score_pertinence DESC
            LIMIT 30
        """).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/alumni")
def api_alumni():
    mem = Memory()
    with mem._connect() as conn:
        rows = conn.execute("""
            SELECT prenom, nom, poste_actuel, entreprise,
                   statut_contact, date_contact, linkedin_url
            FROM alumni
            ORDER BY date_contact DESC NULLS LAST
            LIMIT 30
        """).fetchall()
    return jsonify([dict(r) for r in rows])


# ────────────────────────────────────────────────
# PAGE HTML
# ────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Agent Alternance — Ali Benaqa</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0f1117;
    --card: #1a1d2e;
    --border: #2a2d3e;
    --accent: #6c63ff;
    --accent2: #00d4ff;
    --green: #00c875;
    --orange: #ff9f43;
    --red: #ff6b6b;
    --yellow: #ffd93d;
    --text: #e2e8f0;
    --muted: #64748b;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: var(--bg); color: var(--text); font-family: 'Inter', system-ui, sans-serif; min-height: 100vh; }

  /* HEADER */
  header {
    background: linear-gradient(135deg, var(--card) 0%, #12162a 100%);
    border-bottom: 1px solid var(--border);
    padding: 1.2rem 2rem;
    display: flex; align-items: center; justify-content: space-between;
  }
  .logo { display: flex; align-items: center; gap: 0.75rem; }
  .logo-icon { font-size: 1.8rem; }
  .logo h1 { font-size: 1.25rem; font-weight: 700; }
  .logo p { font-size: 0.75rem; color: var(--muted); }
  .status-live {
    display: flex; align-items: center; gap: 0.5rem;
    background: rgba(0,200,117,0.1); border: 1px solid rgba(0,200,117,0.3);
    padding: 0.4rem 0.9rem; border-radius: 999px; font-size: 0.8rem;
  }
  .dot { width: 8px; height: 8px; background: var(--green); border-radius: 50%; animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }

  /* LAYOUT */
  main { max-width: 1400px; margin: 0 auto; padding: 2rem; }
  .section-title {
    font-size: 0.75rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.1em; color: var(--muted); margin-bottom: 1rem;
  }

  /* STAT CARDS */
  .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem; }
  .stat-card {
    background: var(--card); border: 1px solid var(--border);
    border-radius: 12px; padding: 1.25rem 1.5rem;
    transition: transform 0.2s, border-color 0.2s;
  }
  .stat-card:hover { transform: translateY(-2px); border-color: var(--accent); }
  .stat-card .label { font-size: 0.75rem; color: var(--muted); margin-bottom: 0.5rem; }
  .stat-card .value { font-size: 2rem; font-weight: 800; line-height: 1; }
  .stat-card .sub { font-size: 0.75rem; color: var(--muted); margin-top: 0.4rem; }
  .stat-card.purple .value { color: var(--accent); }
  .stat-card.cyan .value   { color: var(--accent2); }
  .stat-card.green .value  { color: var(--green); }
  .stat-card.orange .value { color: var(--orange); }
  .stat-card.yellow .value { color: var(--yellow); }

  /* GRID 2 COLS */
  .grid-2 { display: grid; grid-template-columns: 2fr 1fr; gap: 1.5rem; margin-bottom: 2rem; }
  @media (max-width: 900px) { .grid-2 { grid-template-columns: 1fr; } }

  /* CARDS */
  .card {
    background: var(--card); border: 1px solid var(--border);
    border-radius: 12px; padding: 1.5rem; overflow: hidden;
  }
  .card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1.25rem; }
  .card-header h2 { font-size: 0.95rem; font-weight: 600; }
  .badge {
    font-size: 0.7rem; font-weight: 600; padding: 0.2rem 0.6rem;
    border-radius: 999px; background: rgba(108,99,255,0.15); color: var(--accent);
  }

  /* TABLE */
  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  thead th { text-align: left; padding: 0.5rem 0.75rem; color: var(--muted); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid var(--border); }
  tbody tr { border-bottom: 1px solid rgba(42,45,62,0.6); transition: background 0.15s; }
  tbody tr:hover { background: rgba(108,99,255,0.05); }
  tbody td { padding: 0.75rem; vertical-align: middle; }
  .company { font-weight: 600; }
  .titre { color: var(--muted); font-size: 0.8rem; }
  .score-bar { display: flex; align-items: center; gap: 0.5rem; }
  .bar { height: 4px; border-radius: 999px; background: var(--border); width: 60px; }
  .bar-fill { height: 100%; border-radius: 999px; background: linear-gradient(90deg, var(--accent), var(--accent2)); }

  /* BADGES STATUT */
  .tag { display: inline-block; font-size: 0.7rem; font-weight: 600; padding: 0.2rem 0.55rem; border-radius: 999px; }
  .tag-postule  { background: rgba(108,99,255,0.15); color: var(--accent); }
  .tag-entretien { background: rgba(0,200,117,0.15); color: var(--green); }
  .tag-interesant { background: rgba(0,212,255,0.15); color: var(--accent2); }
  .tag-envoye   { background: rgba(255,159,67,0.15); color: var(--orange); }
  .tag-refuse   { background: rgba(255,107,107,0.15); color: var(--red); }
  .tag-relance  { background: rgba(255,217,61,0.15); color: var(--yellow); }

  /* CANAL ICONS */
  .canal { font-size: 0.75rem; color: var(--muted); }

  /* CHART */
  .chart-container { position: relative; height: 200px; }

  /* ALUMNI LIST */
  .alumni-list { display: flex; flex-direction: column; gap: 0.75rem; }
  .alumni-item {
    display: flex; align-items: center; gap: 0.75rem;
    padding: 0.75rem; border-radius: 8px; background: rgba(255,255,255,0.02);
    border: 1px solid var(--border);
  }
  .alumni-avatar {
    width: 36px; height: 36px; border-radius: 50%;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 0.85rem; flex-shrink: 0;
  }
  .alumni-info { flex: 1; min-width: 0; }
  .alumni-name { font-size: 0.85rem; font-weight: 600; }
  .alumni-poste { font-size: 0.75rem; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

  /* FOOTER */
  .footer-bar {
    display: flex; align-items: center; justify-content: space-between;
    padding: 1rem 2rem; border-top: 1px solid var(--border);
    font-size: 0.75rem; color: var(--muted);
  }
  #last-update { color: var(--green); }

  /* EMPTY STATE */
  .empty { text-align: center; padding: 2rem; color: var(--muted); font-size: 0.85rem; }

  /* SOURCES */
  .sources-grid { display: flex; flex-direction: column; gap: 0.5rem; }
  .source-row { display: flex; align-items: center; gap: 0.75rem; font-size: 0.8rem; }
  .source-name { width: 120px; color: var(--muted); }
  .source-bar { flex: 1; height: 6px; background: var(--border); border-radius: 999px; overflow: hidden; }
  .source-fill { height: 100%; border-radius: 999px; background: linear-gradient(90deg, var(--accent), var(--accent2)); transition: width 0.5s ease; }
  .source-nb { width: 30px; text-align: right; font-weight: 600; }
</style>
</head>
<body>

<header>
  <div class="logo">
    <div class="logo-icon">🤖</div>
    <div>
      <h1>Agent Alternance</h1>
      <p>Ali Benaqa — Bachelor Data & IA, Hetic</p>
    </div>
  </div>
  <div class="status-live">
    <div class="dot"></div>
    <span>En ligne</span>
  </div>
</header>

<main>

  <!-- STATS CARDS -->
  <div class="section-title">Vue d'ensemble</div>
  <div class="stats-grid" id="stats-cards">
    <div class="stat-card purple"><div class="label">Candidatures totales</div><div class="value" id="s-cands">—</div><div class="sub" id="s-cands-sub">—</div></div>
    <div class="stat-card green"><div class="label">Entretiens obtenus</div><div class="value" id="s-entretiens">—</div><div class="sub" id="s-taux">—</div></div>
    <div class="stat-card cyan"><div class="label">Offres intéressantes</div><div class="value" id="s-interessantes">—</div><div class="sub">en base</div></div>
    <div class="stat-card orange"><div class="label">Alumni contactés</div><div class="value" id="s-alumni">—</div><div class="sub" id="s-alumni-sub">—</div></div>
    <div class="stat-card yellow"><div class="label">Offres scrapées</div><div class="value" id="s-total">—</div><div class="sub">toutes sources</div></div>
  </div>

  <!-- CANDIDATURES + SOURCES -->
  <div class="grid-2">

    <!-- CANDIDATURES TABLE -->
    <div class="card">
      <div class="card-header">
        <h2>📤 Dernières candidatures</h2>
        <span class="badge" id="badge-cands">0</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Entreprise</th>
              <th>Canal</th>
              <th>Statut</th>
              <th>Date</th>
            </tr>
          </thead>
          <tbody id="tbody-cands">
            <tr><td colspan="4" class="empty">Chargement...</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- SOURCES -->
    <div style="display:flex; flex-direction:column; gap:1.5rem;">
      <div class="card">
        <div class="card-header"><h2>📡 Sources de scraping</h2></div>
        <div class="sources-grid" id="sources-grid">
          <div class="empty">Chargement...</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header"><h2>🎓 Alumni Hetic</h2></div>
        <div class="alumni-list" id="alumni-list">
          <div class="empty">Chargement...</div>
        </div>
      </div>
    </div>

  </div>

  <!-- TOP OFFRES -->
  <div class="card" style="margin-bottom:2rem;">
    <div class="card-header">
      <h2>🏆 Top offres</h2>
      <span class="badge" id="badge-offres">0</span>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Poste</th>
            <th>Entreprise</th>
            <th>Lieu</th>
            <th>Source</th>
            <th>Score</th>
            <th>Statut</th>
          </tr>
        </thead>
        <tbody id="tbody-offres">
          <tr><td colspan="6" class="empty">Chargement...</td></tr>
        </tbody>
      </table>
    </div>
  </div>

</main>

<div class="footer-bar">
  <span>🤖 Agent Alternance v2.0 — Auto-refresh toutes les 30s</span>
  <span>Dernière mise à jour : <span id="last-update">—</span></span>
</div>

<script>
const CANALS = { email: "📧 Email", formulaire_web: "🌐 Formulaire", linkedin_easy_apply: "🔗 Easy Apply", formulaire: "🌐 Formulaire" };
const SOURCES_LABELS = { wttj: "WTTJ", linkedin: "LinkedIn", indeed: "Indeed", hellowork: "HelloWork", labonnealternance: "La Bonne Alt.", france_travail: "France Travail", apec: "APEC", turso: "Turso (sync)" };

function tagStatut(statut) {
  const map = {
    "postulé":    ["tag-postule",   "Postulé"],
    "entretien":  ["tag-entretien", "🎉 Entretien"],
    "intéressant":["tag-interesant","Intéressant"],
    "envoyée":    ["tag-envoye",    "Envoyé"],
    "refusé":     ["tag-refuse",    "Refusé"],
    "relance":    ["tag-relance",   "Relancé"],
  };
  const [cls, label] = map[statut] || ["tag-envoye", statut || "—"];
  return `<span class="tag ${cls}">${label}</span>`;
}

function scoreBar(score) {
  const pct = Math.round((score || 0) * 100);
  const color = pct >= 90 ? "#00c875" : pct >= 75 ? "#6c63ff" : "#ff9f43";
  return `<div class="score-bar">
    <div class="bar"><div class="bar-fill" style="width:${pct}%;background:${color}"></div></div>
    <span style="font-size:0.75rem;color:var(--muted)">${pct}%</span>
  </div>`;
}

async function loadStats() {
  try {
    const r = await fetch("/api/stats");
    const d = await r.json();

    document.getElementById("s-cands").textContent = d.total_candidatures ?? 0;
    document.getElementById("s-cands-sub").textContent = `${d.candidatures_semaine ?? 0} cette semaine`;
    document.getElementById("s-entretiens").textContent = d.entretiens ?? 0;
    document.getElementById("s-taux").textContent = `Taux : ${d.taux_reponse ?? 0}%`;
    document.getElementById("s-interessantes").textContent = d.offres_par_statut?.["intéressant"] ?? 0;
    document.getElementById("s-alumni").textContent = d.alumni_contactes ?? 0;
    document.getElementById("s-alumni-sub").textContent = `${d.total_alumni ?? 0} trouvés`;
    document.getElementById("s-total").textContent = d.total_offres ?? 0;
    document.getElementById("last-update").textContent = d.updated_at;

    // Sources
    const sources = d.sources || {};
    const total = Object.values(sources).reduce((a, b) => a + b, 0) || 1;
    const grid = document.getElementById("sources-grid");
    const sorted = Object.entries(sources).sort((a, b) => b[1] - a[1]);
    if (sorted.length === 0) {
      grid.innerHTML = '<div class="empty">Aucune donnée</div>';
    } else {
      grid.innerHTML = sorted.map(([src, nb]) => `
        <div class="source-row">
          <span class="source-name">${SOURCES_LABELS[src] || src}</span>
          <div class="source-bar"><div class="source-fill" style="width:${Math.round(nb/total*100)}%"></div></div>
          <span class="source-nb">${nb}</span>
        </div>`).join("");
    }
  } catch(e) { console.error("Stats:", e); }
}

async function loadCandidatures() {
  try {
    const r = await fetch("/api/candidatures");
    const data = await r.json();
    document.getElementById("badge-cands").textContent = data.length;
    const tbody = document.getElementById("tbody-cands");
    if (!data.length) { tbody.innerHTML = '<tr><td colspan="4" class="empty">Aucune candidature</td></tr>'; return; }
    tbody.innerHTML = data.slice(0, 20).map(c => `
      <tr>
        <td>
          <div class="company">${c.entreprise || "—"}</div>
          <div class="titre">${c.titre || ""}</div>
        </td>
        <td><span class="canal">${CANALS[c.canal] || c.canal || "—"}</span></td>
        <td>${tagStatut(c.statut_offre || c.statut)}</td>
        <td style="color:var(--muted);font-size:0.75rem">${(c.date_candidature||"").slice(0,10)}</td>
      </tr>`).join("");
  } catch(e) { console.error("Cands:", e); }
}

async function loadOffres() {
  try {
    const r = await fetch("/api/offres");
    const data = await r.json();
    document.getElementById("badge-offres").textContent = data.length;
    const tbody = document.getElementById("tbody-offres");
    if (!data.length) { tbody.innerHTML = '<tr><td colspan="6" class="empty">Aucune offre</td></tr>'; return; }
    tbody.innerHTML = data.slice(0, 15).map(o => `
      <tr>
        <td><a href="${o.url||'#'}" target="_blank" style="color:var(--accent2);text-decoration:none">${o.titre||"—"}</a></td>
        <td class="company">${o.entreprise||"—"}</td>
        <td style="color:var(--muted);font-size:0.75rem">${o.localisation||"—"}</td>
        <td><span style="font-size:0.7rem;color:var(--muted)">${SOURCES_LABELS[o.source]||o.source||""}</span></td>
        <td>${scoreBar(o.score_pertinence)}</td>
        <td>${tagStatut(o.statut)}</td>
      </tr>`).join("");
  } catch(e) { console.error("Offres:", e); }
}

async function loadAlumni() {
  try {
    const r = await fetch("/api/alumni");
    const data = await r.json();
    const list = document.getElementById("alumni-list");
    const contactes = data.filter(a => a.statut_contact !== "non contacté");
    if (!contactes.length) { list.innerHTML = '<div class="empty">Aucun alumni contacté</div>'; return; }
    list.innerHTML = contactes.slice(0, 5).map(a => {
      const initials = ((a.prenom||"?")[0] + (a.nom||"?")[0]).toUpperCase();
      const statusColor = a.statut_contact === "répondu" ? "var(--green)" : "var(--accent)";
      return `<div class="alumni-item">
        <div class="alumni-avatar">${initials}</div>
        <div class="alumni-info">
          <div class="alumni-name">${a.prenom||""} ${a.nom||""}</div>
          <div class="alumni-poste">${a.poste_actuel||""} @ ${a.entreprise||""}</div>
        </div>
        <span class="tag" style="background:rgba(108,99,255,0.1);color:${statusColor}">${a.statut_contact||""}</span>
      </div>`;
    }).join("");
  } catch(e) { console.error("Alumni:", e); }
}

async function refresh() {
  await Promise.all([loadStats(), loadCandidatures(), loadOffres(), loadAlumni()]);
}

refresh();
setInterval(refresh, 30000); // auto-refresh toutes les 30s
</script>
</body>
</html>"""


@app.route("/")
def index():
    return render_template_string(HTML)


# ────────────────────────────────────────────────
# LANCEMENT EN THREAD DEPUIS MAIN.PY
# ────────────────────────────────────────────────

def start_dashboard():
    """Lance le serveur Flask dans un thread daemon."""
    thread = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False),
        daemon=True,
        name="dashboard",
    )
    thread.start()
    return thread


if __name__ == "__main__":
    print(f"🌐 Dashboard lancé sur http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=True)
