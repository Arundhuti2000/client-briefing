"""Pre-review of the retrieval labels (written with AI assistance; human review pending): for every question, the labelled relevant
documents and the top 5 hybrid results (the ranking the app uses), each with its title, so a
person can judge whether a label is missing or wrong. It never changes the labels.

Writes the review to stdout as Markdown; eval/LABEL_REVIEW.md is that output plus notes from an automated
pre-review (Claude Code), for the developer to review.
Run:  python -m eval.label_review > review.md
"""

import tempfile
from contextlib import closing
from pathlib import Path

import yaml

from app import db, tools
from app.retrieval import load_embeddings
from eval import run_eval
from eval.quality import K, rank, ranked_docs

DATASETS = {"dev": "Dev", "dev2": "Dev 2", "holdout": "Holdout"}


def title_of(chunks: list) -> dict[str, str]:
    """doc_id -> 'Subject or headline (date)', from the document's first chunk."""
    titles = {}
    for c in chunks:
        if c["doc_id"] not in titles:
            first_line = c["text"].strip().splitlines()[0].lstrip("# ").strip()
            titles[c["doc_id"]] = f"{first_line[:70]} ({c['date']})"
    return titles


def review(dataset: str) -> list[str]:
    questions = yaml.safe_load(run_eval.RETRIEVAL_SETS[dataset].read_text(encoding="utf-8"))
    lines = [f"## {DATASETS[dataset]} (`{run_eval.RETRIEVAL_SETS[dataset].relative_to(run_eval.EVAL_DIR.parent).as_posix()}`)", ""]
    with closing(db.connect()) as conn:
        vectors = load_embeddings(db.DB_PATH.parent)
        for n, q in enumerate(questions, 1):
            user = tools.load_user(q.get("user", "u2"))
            candidates = db.visible_chunks(conn, q["client"], user.entitlements)
            by_id = {c["chunk_id"]: c for c in candidates}
            titles = title_of(candidates)
            top = ranked_docs(rank("hybrid", candidates, q["question"], vectors), by_id)[:K]
            relevant = q["relevant"]
            lines.append(f"### {n}. {q['question']}  ({q['client']}, as {q.get('user', 'u2')})")
            lines.append(f"- Labelled relevant: {', '.join(f'`{d}`' for d in relevant) or 'none (nothing should be found)'}")
            lines.append("- Hybrid top 5:")
            for i, doc in enumerate(top, 1):
                lines.append(f"  {i}. `{doc}` {'(labelled) ' if doc in relevant else ''}{titles.get(doc, '')}")
            if not top:
                lines.append("  (nothing returned)")
            missing = [d for d in relevant if d not in top]
            lines.append(f"- Check: {'labelled docs not in the top 5: ' + ', '.join(missing) if missing else 'every labelled doc is in the top 5'}.")
            lines.append("")
    return lines


def main() -> None:
    out = []
    for dataset in DATASETS:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            run_eval.build_fresh_data(Path(tmp), dataset)
            out += review(dataset)
    print("\n".join(out))


if __name__ == "__main__":
    main()
