# Zuha & Aneeq Ledger (Streamlit)

A private web app where Zuha and Aneeq each sign in with Google, upload PDF bank and card statements, and see the same up-to-date ledger:

- **Overview**: spent from Chase (Zuha), spent from Wells Fargo (Aneeq), what's owed to Zuha, and spending by Core / Extras I / Extras II per account, with each big expense named.
- **Budget**: every line against the monthly plan from the budget sheet, net of money set aside for big expenses. Budget amounts are editable.
- **Transactions**: change a charge's line, tag it to a ★ big expense and item, override who it counts toward, or make a rule for a merchant.
- **Big expenses**: estimated and spent so far (from statements), overall and per item, plus how each is funded.
- **Settle up**: month by month and a running balance.
- **Statements**: upload PDFs; Claude reads them, you confirm, and the original PDF is kept in Google Drive.
- **Rules**: accounts and who pays them, transfers between you, store rules (Costco/Walmart/H-E-B/Kroger → Grocery), merchant rules, line owners.

Spending comes only from statements. Budgets and estimates come only from the budget sheet.

## What it costs

- Streamlit Community Cloud hosting: free.
- Google Drive and Sheets: free (uses your existing Google storage).
- Claude API for reading statements: pay-as-you-go, typically a few cents per statement.

## Setup (about 30 minutes, once)

### 1. Google Cloud project
1. Go to <https://console.cloud.google.com>, create a project (e.g. "Household ledger").
2. **APIs & Services → Library**: enable **Google Drive API** and **Google Sheets API**.
3. **APIs & Services → OAuth consent screen** (Google Auth Platform): choose **External**, fill in the app name and your email.
   - Under **Data access / Scopes**, add `.../auth/drive.file`, `openid`, `email`, `profile`.
   - Under **Audience**, click **Publish app** so its status is **In production**. While an app is in "Testing", Google expires its saved sign-in after 7 days and the app would stop being able to reach the sheet. `drive.file` doesn't need Google's verification review; you'll just see an "unverified app" notice once when you sign in.
4. **Credentials → Create credentials → OAuth client ID**, twice:
   - **Desktop app** named "Ledger data". Download its JSON as `client_secret.json`. Used once in step 2 to connect the app to your Drive.
   - **Web application** named "Ledger sign-in". Add authorized redirect URIs `http://localhost:8501/oauth2callback` and (after step 5) `https://YOUR-APP.streamlit.app/oauth2callback`. Keep its client ID and secret for `[auth.google]`.

### 2. Create the ledger's sheet and statements folder
On your computer:
```bash
pip install google-auth-oauthlib google-api-python-client
python get_google_token.py client_secret.json
```
Sign in with the Google account that should own the data (Zuha's). The script creates a **Ledger statements** folder and a **Zuha & Aneeq Ledger data** sheet in your Drive, shares both with Aneeq, and prints a `[google]` block for the secrets.

### 3. Anthropic API key
Create one at <https://console.anthropic.com> → API keys, and add a small amount of credit. Put it under `[anthropic]`.

### 4. Put the code on GitHub
Create a **private** repository and push this folder. `.gitignore` already keeps `secrets.toml`, `seed_data.json` and local data out of it.

### 5. Deploy on Streamlit Community Cloud
1. Go to <https://share.streamlit.io>, sign in with GitHub, **Create app** → pick the repo, branch, and `app.py`.
2. Under **Advanced settings → Secrets**, paste the contents of `.streamlit/secrets.toml.example`, filled in:
   - `[people]`: already filled in with zuha.m.shaikh@gmail.com and aneeqc@gmail.com (the app uses these two even if you leave the section out).
   - `[auth]`: `redirect_uri = "https://YOUR-APP.streamlit.app/oauth2callback"`, and a long random `cookie_secret` (e.g. `python -c "import secrets; print(secrets.token_hex(32))"`).
   - `[auth.google]`: the Web client's ID and secret.
   - `[google]`: the block printed in step 2.
   - `[anthropic]`: your API key.
3. Deploy. Copy the app's address into the Web client's redirect URIs (step 1.4) if you haven't already.
4. In the app's settings on Streamlit, set sharing so only people you invite can view it. The Google sign-in check in the app is the main lock either way: only the two emails in `[people]` get in.

### 6. Bring in what you already have
Open the app, sign in, and on the first screen upload `seed_data.json` (sent separately; it holds your budget plan, rules, big expenses and the 202 transactions already in the ledger). Don't put that file in GitHub.

## Using it
- **Adding statements**: Statements → choose PDFs → Read statements → check the totals line (it says whether Claude's total matches the statement's own) → pick whose account it is the first time → Add to ledger. Re-adding the same statement skips transactions already there.
- **Both of you see changes** within a minute; use **Refresh data** in the sidebar to see them right away.
- The app sleeps after a few days with no visitors; opening it wakes it in under a minute.

## Run locally
```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # fill in, or leave out [auth]/[google] to test
streamlit run app.py
```
Without `[google]`, data is kept in `.data/` on your computer. Without `[auth]`, there's no sign-in (local testing only).

## Later: connecting Chase and Wells Fargo directly
The data model already has an account per transaction and dedupes repeats, so a bank feed (SimpleFIN Bridge or Teller) can be added as another way in next to PDFs.
