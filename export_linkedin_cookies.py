"""
Exporte les cookies LinkedIn depuis ton vrai Chrome vers Turso.
Lance ce script sur ton Mac, sans rien faire d'autre.

Usage:
    venv/bin/pip install rookiepy
    venv/bin/python export_linkedin_cookies.py
"""

import json
import os
import requests

TURSO_URL   = os.environ.get("TURSO_URL", "https://alternancebot-alibenaqa.aws-eu-west-1.turso.io")
TURSO_TOKEN = os.environ.get("TURSO_TOKEN", "")


def _turso(sql, args=None):
    stmt = {"sql": sql}
    if args:
        stmt["args"] = [{"type": "text", "value": str(a)} for a in args]
    resp = requests.post(
        f"{TURSO_URL}/v2/pipeline",
        headers={"Authorization": f"Bearer {TURSO_TOKEN}", "Content-Type": "application/json"},
        json={"requests": [{"type": "execute", "stmt": stmt}, {"type": "close"}]},
        timeout=15,
    )
    return resp.json()


def main():
    try:
        import rookiepy
    except ImportError:
        print("❌ rookiepy non installé. Lance d'abord :")
        print("   venv/bin/pip install rookiepy")
        return

    print("🍪 Extraction des cookies LinkedIn depuis Chrome...")
    cookies_raw = rookiepy.chrome(["linkedin.com"])

    # Convertit au format Playwright
    cookies = []
    for c in cookies_raw:
        cookies.append({
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", ".linkedin.com"),
            "path": c.get("path", "/"),
            "secure": c.get("secure", True),
            "httpOnly": c.get("httpOnly", False),
        })

    print(f"✅ {len(cookies)} cookies extraits")

    _turso("CREATE TABLE IF NOT EXISTS linkedin_cookies (id INTEGER PRIMARY KEY, data TEXT, updated_at TEXT DEFAULT (datetime('now')))")
    _turso("DELETE FROM linkedin_cookies")
    _turso("INSERT INTO linkedin_cookies (data) VALUES (?)", [json.dumps(cookies)])

    print("✅ Cookies sauvegardés dans Turso !")
    print("   → Envoie /linkedin_session sur Telegram.")


if __name__ == "__main__":
    main()
