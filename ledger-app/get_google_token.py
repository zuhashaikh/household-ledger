"""One-time Google setup. Run on your own computer:

    pip install google-auth-oauthlib google-api-python-client
    python get_google_token.py client_secret.json

It opens a browser to sign in to the Google account that should own the ledger data, then:
  - creates a Drive folder "Ledger statements" and a sheet "Zuha & Aneeq Ledger data" inside it,
  - shares both with Aneeq (aneeqc@gmail.com) so he can open them in Drive too,
  - prints the [google] block to paste into the app's secrets.

The app only gets the drive.file permission: it can see the files it created here and nothing else in your Drive.
"""
import sys

SHARE_WITH = "aneeqc@gmail.com"

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python get_google_token.py client_secret.json [email to share with, default aneeqc@gmail.com]")
    flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    drive = build("drive", "v3", credentials=creds)

    folder = drive.files().create(body={"name": "Ledger statements", "mimeType": "application/vnd.google-apps.folder"},
                                  fields="id").execute()
    sheet = drive.files().create(body={"name": "Zuha & Aneeq Ledger data", "mimeType": "application/vnd.google-apps.spreadsheet",
                                       "parents": [folder["id"]]}, fields="id").execute()
    share = sys.argv[2] if len(sys.argv) > 2 else SHARE_WITH
    for fid in (folder["id"], sheet["id"]):
        drive.permissions().create(fileId=fid, body={"type": "user", "role": "writer", "emailAddress": share},
                                   sendNotificationEmail=False).execute()
    print(f"Shared the folder and sheet with {share}.")

    print("\nPaste this into your app's secrets:\n")
    print("[google]")
    print(f'client_id = "{creds.client_id}"')
    print(f'client_secret = "{creds.client_secret}"')
    print(f'refresh_token = "{creds.refresh_token}"')
    print(f'spreadsheet_id = "{sheet["id"]}"')
    print(f'folder_id = "{folder["id"]}"')


if __name__ == "__main__":
    main()
