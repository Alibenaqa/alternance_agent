"""
Script one-shot pour générer le refresh token Gmail.
Lance une seule fois en local, puis supprime ce fichier.
"""

from google_auth_oauthlib.flow import InstalledAppFlow

CLIENT_ID     = "243098298551-dt7dtfcc6odnnslkn67gnpmt8ukl3kf5.apps.googleusercontent.com"
CLIENT_SECRET = "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"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

client_config = {
    "installed": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}

flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
creds = flow.run_local_server(port=8090)

print("\n" + "="*60)
print("✅ REFRESH TOKEN OBTENU :")
print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")
print("="*60)
