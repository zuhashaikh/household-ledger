"""Where the ledger lives: a Google Sheet (data) plus a Drive folder (statement PDFs).

LocalStore keeps the same data in a JSON file and is used when Google isn't configured (local testing).
"""
from __future__ import annotations

import io
import json
import os
import time

TX_COLS = ["id", "month", "date", "desc", "spend", "category", "account", "mk", "cat_override", "person",
           "project", "proj_item", "for_line", "moved_from", "statement_id", "added_by"]
ST_COLS = ["id", "filename", "account", "period_start", "period_end", "uploaded_by", "uploaded_at", "file_id",
           "n_added", "n_skipped", "file_hash"]
CONFIG_KEYS = ["rules", "plan", "projects"]


def _tx_from_row(d: dict) -> dict:
    t = {k: v for k, v in d.items() if v not in ("", None)}
    t["spend"] = float(t.get("spend") or 0)
    return t


def _tx_to_row(t: dict) -> list:
    return [("" if t.get(c) is None else (round(t[c], 2) if c == "spend" else str(t[c]))) for c in TX_COLS]


class LocalStore:
    kind = "local"

    def __init__(self, path: str = ".data/ledger.json"):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.pdf_dir = os.path.join(os.path.dirname(path) or ".", "statements")
        os.makedirs(self.pdf_dir, exist_ok=True)

    def _read(self) -> dict:
        if not os.path.exists(self.path):
            return {"config": {}, "transactions": [], "statements": []}
        with open(self.path) as f:
            return json.load(f)

    def _write(self, d: dict):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, self.path)

    def load(self) -> dict:
        d = self._read()
        return {"config": d.get("config", {}), "txns": [_tx_from_row(t) for t in d.get("transactions", [])],
                "statements": d.get("statements", [])}

    def save_config(self, key: str, value):
        d = self._read()
        d.setdefault("config", {})[key] = value
        self._write(d)

    def save_txns(self, txns: list[dict]):
        d = self._read()
        d["transactions"] = [dict(zip(TX_COLS, _tx_to_row(t))) for t in txns]
        self._write(d)

    def add_statement(self, meta: dict, pdf: bytes) -> dict:
        fname = f"{meta['id']}.pdf"
        with open(os.path.join(self.pdf_dir, fname), "wb") as f:
            f.write(pdf)
        meta = {**meta, "file_id": fname}
        d = self._read()
        d.setdefault("statements", []).append(meta)
        self._write(d)
        return meta

    def get_pdf(self, meta: dict) -> bytes:
        with open(os.path.join(self.pdf_dir, meta["file_id"]), "rb") as f:
            return f.read()


class GoogleStore:
    """Sheet tabs: transactions, statements, config (key | JSON). PDFs go to one Drive folder.

    Uses the account owner's OAuth refresh token with the drive.file scope, so the app can only see the
    sheet and folder that setup created.
    """
    kind = "google"
    SCOPES = ["https://www.googleapis.com/auth/drive.file"]

    def __init__(self, cfg: dict):
        import gspread
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        self.creds = Credentials(None, refresh_token=cfg["refresh_token"], token_uri="https://oauth2.googleapis.com/token",
                                 client_id=cfg["client_id"], client_secret=cfg["client_secret"], scopes=self.SCOPES)
        self.gc = gspread.authorize(self.creds)
        self.sh = self.gc.open_by_key(cfg["spreadsheet_id"])
        self.folder_id = cfg["folder_id"]
        self.drive = build("drive", "v3", credentials=self.creds, cache_discovery=False)
        self._ws = {}

    def _tab(self, name: str, header: list[str]):
        if name in self._ws:
            return self._ws[name]
        import gspread
        try:
            ws = self.sh.worksheet(name)
            have = ws.row_values(1)
            if have and have != header[:len(have)] or len(have) < len(header):
                # Older sheet: add any new columns to the header row (new columns always go at the end).
                merged = have + [c for c in header if c not in have]
                if ws.col_count < len(merged):
                    ws.add_cols(len(merged) - ws.col_count)
                ws.update(values=[merged], range_name="A1", value_input_option="RAW")
        except gspread.WorksheetNotFound:
            ws = self.sh.add_worksheet(title=name, rows=1000, cols=max(len(header), 2))
            ws.update(values=[header], range_name="A1", value_input_option="RAW")
        self._ws[name] = ws
        return ws

    @staticmethod
    def _records(ws) -> list[dict]:
        vals = ws.get_all_values()
        if not vals:
            return []
        head = vals[0]
        return [dict(zip(head, r)) for r in vals[1:] if any(c != "" for c in r)]

    def _rewrite(self, ws, header: list[str], rows: list[list]):
        ws.clear()
        need = len(rows) + 50
        if ws.row_count < need:
            ws.add_rows(need - ws.row_count)
        ws.update(values=[header] + rows, range_name="A1", value_input_option="RAW")

    def load(self) -> dict:
        cfg = {}
        for r in self._records(self._tab("config", ["key", "value"])):
            try:
                cfg[r["key"]] = json.loads(r["value"])
            except (json.JSONDecodeError, KeyError):
                pass
        txns = [_tx_from_row(r) for r in self._records(self._tab("transactions", TX_COLS))]
        sts = self._records(self._tab("statements", ST_COLS))
        return {"config": cfg, "txns": txns, "statements": sts}

    def save_config(self, key: str, value):
        ws = self._tab("config", ["key", "value"])
        recs = {r["key"]: r["value"] for r in self._records(ws)}
        recs[key] = json.dumps(value)
        self._rewrite(ws, ["key", "value"], [[k, v] for k, v in recs.items()])

    def save_txns(self, txns: list[dict]):
        self._rewrite(self._tab("transactions", TX_COLS), TX_COLS, [_tx_to_row(t) for t in txns])

    def add_statement(self, meta: dict, pdf: bytes) -> dict:
        from googleapiclient.http import MediaIoBaseUpload
        f = self.drive.files().create(
            body={"name": meta["filename"], "parents": [self.folder_id]},
            media_body=MediaIoBaseUpload(io.BytesIO(pdf), mimetype="application/pdf", resumable=False),
            fields="id").execute()
        meta = {**meta, "file_id": f["id"]}
        ws = self._tab("statements", ST_COLS)
        head = ws.row_values(1) or ST_COLS
        ws.append_row([str(meta.get(c, "")) for c in head], value_input_option="RAW")
        return meta

    def get_pdf(self, meta: dict) -> bytes:
        return self.drive.files().get_media(fileId=meta["file_id"]).execute()


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")
