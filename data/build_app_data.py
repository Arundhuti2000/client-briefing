"""`make data`: every dataset the app shows, written into data/ (then `make unify` loads it).

  1. The dev data (data/generate_data.py): Northwind, Helios, Arbor; users u1 Alex, u2 Sam.
  2. dev2 (data/generate_dev2.py, held-out round 1): Harbor & Pine Foods, Kestrel Aviation,
     Copperleaf Dental; users u3 Nadia Rahman, u4 Daniel Osei; trap IDs D2T1-D2T12.
  3. The held-out data, round 2 (data/generate_holdout.py): Vossberg, Lattice Ridge, Cedar
     Hollow; users u5 Sofia Marchetti, u6 Kwame Mensah; trap IDs HT1-HT12.
  4. The red-team documents (eval/redteam/): hidden instructions the briefing must ignore.

Each added dataset's users are renumbered after the ones already there, so Alex and Sam keep
their IDs, and its trap IDs get a prefix, so the answer keys don't clash. `make eval` never
reads data/: it builds each dataset on its own in a temp folder, so each is scored separately.

Run:  make data   (or: python -m data.build_app_data)
"""

import csv
import json
import shutil
from pathlib import Path

from data import generate_data as gd, generate_dev2, generate_holdout

DATA_DIR = Path(__file__).resolve().parent
REDTEAM_DIR = DATA_DIR.parent / "eval" / "redteam"


def read_csv(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def renumber_users(rows: list[list[str]], taken: int) -> list[list[str]]:
    """An added dataset's u1, u2 become u3, u4 (or u5, u6): after the users already there."""
    new_id = {old: f"u{taken + i}" for i, old in enumerate(sorted(r[0] for r in rows), 1)}
    return [[new_id[r[0]], *r[1:]] for r in rows]


def add_dataset(data_dir: Path, extra_dir: Path, trap_prefix: str) -> None:
    """Append another generated dataset to the one in data_dir: CSV rows, documents,
    claims and traps. The asserts stop the build if the CSV columns differ or a document or
    claim ID is in both datasets; CSV record IDs are kept apart by each generator's ID ranges,
    and a row identical in both (such as a shared approved news source) is added once."""
    raw, extra_raw = data_dir / "raw", extra_dir / "raw"
    for extra_csv in sorted(extra_raw.glob("*.csv")):
        existing = read_csv(raw / extra_csv.name)
        header, *rows = read_csv(extra_csv)
        assert header == existing[0], f"{extra_csv.name}: the two datasets have different columns"
        if extra_csv.name == "iam_users.csv":
            rows = renumber_users(rows, taken=len(existing) - 1)
        rows = [r for r in rows if r not in existing]  # e.g. a news source both datasets approve
        with (raw / extra_csv.name).open("a", newline="", encoding="utf-8") as f:
            csv.writer(f, lineterminator="\n").writerows(rows)

    for doc in sorted((extra_raw / "docs").rglob("*.*")):
        target = raw / "docs" / doc.relative_to(extra_raw / "docs")
        assert not target.exists(), f"{target.name} is in both datasets"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(doc, target)

    claims, extra_claims = read_json(data_dir / "extracted_claims.json"), read_json(extra_dir / "extracted_claims.json")
    assert not claims.keys() & extra_claims.keys(), "a doc_id is in both datasets"
    write_json(data_dir / "extracted_claims.json", claims | extra_claims)

    extra_traps = [trap | {"trap_id": trap_prefix + trap["trap_id"]} for trap in read_json(extra_dir / "planted_traps.json")]
    write_json(data_dir / "planted_traps.json", read_json(data_dir / "planted_traps.json") + extra_traps)


def add_red_team_documents(data_dir: Path) -> None:
    """eval/redteam/<doc_type>/<file> -> data/raw/docs/<doc_type>/<file>, as make eval does."""
    for doc in sorted(REDTEAM_DIR.glob("*/*.*")):
        target = data_dir / "raw" / "docs" / doc.parent.name / doc.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(doc, target)


def build(data_dir: Path = DATA_DIR, dev2_dir: Path = generate_dev2.DEV2_DIR,
          holdout_dir: Path = generate_holdout.HOLDOUT_DIR) -> None:
    gd.generate(data_dir)                 # starts data/raw from scratch, so reruns are identical
    generate_dev2.generate(dev2_dir)
    add_dataset(data_dir, dev2_dir, trap_prefix="D2")
    generate_holdout.generate(holdout_dir)
    add_dataset(data_dir, holdout_dir, trap_prefix="H")
    add_red_team_documents(data_dir)


if __name__ == "__main__":
    build()
    clients = len(read_csv(DATA_DIR / "raw" / "crm_clients.csv")) - 1
    users = [f"{r[0]} {r[1]}" for r in read_csv(DATA_DIR / "raw" / "iam_users.csv")[1:]]
    docs = len(list((DATA_DIR / "raw" / "docs").rglob("*.*")))
    print(f"Wrote dev + dev2 + held-out + red-team data to {DATA_DIR / 'raw'}: {clients} client records, "
          f"{docs} documents, users {', '.join(users)}. Next: make unify")
