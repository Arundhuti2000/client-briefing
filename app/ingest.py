"""Load every document format into one Document model (docs/DATA.md#raw-sources-and-formats).

Each source system keeps its own format, in a folder of data/raw/docs/ named
after its doc_type:
  email/*.eml           headers: From (author), Date, Subject, X-Client-Ref
  meeting_note/*.md     YAML front matter with all the metadata
  prior_briefing/*.md   (same)
  research/*.md         (same)
  news/*.txt            header lines: Source, Date, Headline, optional Client-Ref

The file name is the doc_id. Claims come from extracted_claims.json, keyed by
doc_id. Everything after this module works with Document only, so it never
needs to know which format a document arrived in.

Run:  python -m app.ingest   (prints one line per loaded document)
"""

import datetime as dt
import json
from email import message_from_string, policy
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DOCS_DIR = DATA_DIR / "raw" / "docs"
CLAIMS_PATH = DATA_DIR / "extracted_claims.json"


class Document(BaseModel):
    doc_id: str
    doc_type: Literal["email", "meeting_note", "prior_briefing", "research", "news"]
    client_ref: str | None  # an ID, an alias, or missing
    date: dt.date
    author: str | None
    source: str
    restricted: bool
    required_entitlement: str
    text: str
    claims: list[dict] = []


def parse_email(path: Path) -> dict:
    """An .eml file, read with Python's standard email library.
    Emails carry no entitlement header, so they load as unrestricted."""
    msg = message_from_string(path.read_text(encoding="utf-8"), policy=policy.default)
    client_ref = msg["X-Client-Ref"]
    return {
        "client_ref": str(client_ref) if client_ref else None,
        "date": msg["Date"].datetime.date(),
        "author": msg["From"].addresses[0].display_name,
        "source": "email",
        "restricted": False,
        "required_entitlement": "standard",
        "text": f"{msg['Subject']}\n\n{msg.get_content().strip()}",
    }


def parse_markdown(path: Path) -> dict:
    """A .md file: YAML front matter between two '---' lines, then the body."""
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        raise ValueError(f"{path.name}: missing YAML front matter")
    _, front_matter, body = raw.split("---\n", 2)
    meta = yaml.safe_load(front_matter)  # safe_load: never runs code from the file
    return {
        "client_ref": meta.get("client_ref"),
        "date": meta["date"],
        "author": meta.get("author"),
        "source": meta["source"],
        "restricted": meta["restricted"],
        "required_entitlement": meta["required_entitlement"],
        "text": body.strip(),
    }


def parse_news(path: Path) -> dict:
    """A .txt news item: 'Key: value' header lines, a blank line, then the story.
    News is public, so it loads as unrestricted."""
    header, body = path.read_text(encoding="utf-8").split("\n\n", 1)
    fields = dict(line.split(": ", 1) for line in header.splitlines())
    return {
        "client_ref": fields.get("Client-Ref"),  # missing when the feed tagged no client
        "date": fields["Date"],
        "author": None,
        "source": fields["Source"],
        "restricted": False,
        "required_entitlement": "standard",
        "text": f"{fields['Headline']}\n\n{body.strip()}",
    }


PARSERS = {".eml": parse_email, ".md": parse_markdown, ".txt": parse_news}


def load_documents(docs_dir: Path = DOCS_DIR, claims_path: Path = CLAIMS_PATH) -> list[Document]:
    """Parse every document file and attach its claims. Bad files raise an error."""
    claims = json.loads(claims_path.read_text(encoding="utf-8"))
    documents = []
    for path in sorted(docs_dir.rglob("*")):
        parser = PARSERS.get(path.suffix)
        if parser is None:
            continue  # not a document (e.g. a stray .gitkeep)
        documents.append(Document(
            doc_id=path.stem,
            doc_type=path.parent.name,  # the folder names the doc_type
            claims=claims.get(path.stem, []),
            **parser(path),
        ))
    return documents


def main() -> None:
    for d in load_documents():
        flags = "restricted" if d.restricted else ""
        print(f"{d.doc_id:<14}{d.doc_type:<16}{d.client_ref or '(missing)':<28}{d.date}  "
              f"claims={len(d.claims)}  {flags}")


if __name__ == "__main__":
    main()
