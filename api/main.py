"""FastAPI: thin endpoints over app/ (SPEC.md section 6).

All logic stays in app/. Endpoints and CORS are built in Phase 5.
"""

from fastapi import FastAPI

app = FastAPI(title="Client Briefing Intelligence")
