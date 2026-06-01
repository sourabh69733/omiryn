from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from omiryn.matching import AgePreference, Dealbreaker, MatchProfile, score_match

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="Omiryn API",
    version="0.1.0",
    description="AI-assisted matchmaking platform API.",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/demo/matches")
def demo_matches() -> dict[str, object]:
    user = MatchProfile(
        id="user-demo",
        age=29,
        age_preference=AgePreference(min=26, max=33),
        relationship_intent="long_term",
        values=["family", "ambition", "emotional_stability"],
        lifestyle=["fitness", "travel", "balanced_work"],
        communication_style="direct",
        religion_importance="medium",
        family_involvement="medium",
        children_preference="wants_children",
        city="Bengaluru",
        dealbreakers=[Dealbreaker(type="smoking", severity="hard")],
        attributes=["vegetarian", "non_smoker"],
    )
    candidates = [
        MatchProfile(
            id="match-1",
            age=28,
            age_preference=AgePreference(min=28, max=34),
            relationship_intent="marriage",
            values=["family", "ambition", "kindness"],
            lifestyle=["fitness", "travel", "early_riser"],
            communication_style="direct",
            religion_importance="medium",
            family_involvement="medium",
            children_preference="wants_children",
            city="Bengaluru",
            dealbreakers=[Dealbreaker(type="heavy_drinking", severity="hard")],
            attributes=["non_smoker"],
        ),
        MatchProfile(
            id="match-2",
            age=31,
            age_preference=AgePreference(min=27, max=35),
            relationship_intent="long_term",
            values=["curiosity", "family", "calm"],
            lifestyle=["travel", "balanced_work", "reading"],
            communication_style="reflective",
            religion_importance="low",
            family_involvement="medium",
            children_preference="open",
            city="Mumbai",
            open_to_relocation=True,
            dealbreakers=[],
            attributes=["non_smoker"],
        ),
        MatchProfile(
            id="match-3",
            age=27,
            age_preference=AgePreference(min=29, max=36),
            relationship_intent="casual",
            values=["adventure", "independence"],
            lifestyle=["nightlife"],
            communication_style="spontaneous",
            city="Bengaluru",
            attributes=["smoking"],
        ),
    ]

    names = {
        "match-1": "Meera",
        "match-2": "Isha",
        "match-3": "Rhea",
    }

    return {
        "matches": [
            {
                "id": candidate.id,
                "name": names[candidate.id],
                "age": candidate.age,
                "city": candidate.city,
                "result": score_match(user, candidate),
            }
            for candidate in candidates
        ]
    }
