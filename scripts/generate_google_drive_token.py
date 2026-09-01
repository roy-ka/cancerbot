#!/usr/bin/env python3
"""
One-time interactive Google Drive OAuth authorization.

Run this ONCE on a machine with a browser (your laptop, NOT the server) to
produce the token file that backup_db.py/backup_opensearch.py's --drive
upload uses. It opens a browser, you approve access to your own Drive, and
it writes a token (including a refresh token) to disk. scp that file to the
server afterward and point GOOGLE_OAUTH_TOKEN_FILE at it — the backup
scripts auto-refresh the access token from then on, no browser needed again
unless you revoke access.

Usage:
  python scripts/generate_google_drive_token.py \
      --client-secret /path/to/client_secret.json \
      --out drive_token.json

`client_secret.json` comes from Google Cloud Console: APIs & Services ->
Credentials -> Create Credentials -> OAuth client ID -> Desktop app ->
Download JSON.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.backup_drive import SCOPES


def main():
    parser = argparse.ArgumentParser(description="Generate a Google Drive OAuth token")
    parser.add_argument("--client-secret", required=True, help="Path to client_secret.json from Cloud Console")
    parser.add_argument("--out", default="drive_token.json", help="Where to write the resulting token")
    args = parser.parse_args()

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(args.client_secret, SCOPES)
    creds = flow.run_local_server(port=0)

    with open(args.out, "w") as f:
        f.write(creds.to_json())

    print(f"✓ Token saved to {args.out}")
    print("  scp this file to the server and set GOOGLE_OAUTH_TOKEN_FILE to its path there.")
    print("  Do not commit it — it grants access to your Drive.")


if __name__ == "__main__":
    main()
