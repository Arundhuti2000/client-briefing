"""make data: the app gets the dev clients, the held-out clients and the red-team documents."""

import sqlite3

from app import db, tools, unify
from data import build_app_data


def test_the_app_data_holds_every_dataset_and_keeps_entitlements(tmp_path, monkeypatch):
    build_app_data.build(tmp_path / "app", dev2_dir=tmp_path / "dev2", holdout_dir=tmp_path / "holdout")
    unify.run(tmp_path / "app")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "app" / "briefing.db")
    conn = sqlite3.connect(db.DB_PATH)

    clients = [cid for (cid,) in conn.execute("SELECT client_id FROM clients ORDER BY client_id")]
    # C014, C219 and C318 merged as duplicates
    assert clients == ["C001", "C002", "C003", "C201", "C202", "C203", "C301", "C302", "C303"]
    users = dict(conn.execute("SELECT user_id, name FROM users"))
    assert users == {"u1": "Alex Morgan", "u2": "Sam Rivera", "u3": "Nadia Rahman", "u4": "Daniel Osei",
                     "u5": "Sofia Marchetti", "u6": "Kwame Mensah"}
    traps = [t for (t,) in conn.execute("SELECT trap_id FROM planted_traps")]
    assert len(traps) == len(set(traps)) == 36 and {"T1", "D2T1", "HT1"} <= set(traps)
    assert conn.execute("SELECT COUNT(*) FROM chunks WHERE doc_id = 'email_901'").fetchone()[0]  # red team

    def opportunities(user_id: str, client_id: str) -> list[str]:
        return [f.evidence_id for f in tools.get_opportunities(tools.load_user(user_id), client_id=client_id).facts]
    for client_id, restricted in (("C202", "OPP-KAS-ACQ"), ("C301", "OPP-VOS-MA")):
        assert f"SQL:opportunities:{restricted}" in opportunities("u1", client_id)      # Alex may see it
        assert f"SQL:opportunities:{restricted}" not in opportunities("u2", client_id)  # Sam may not
