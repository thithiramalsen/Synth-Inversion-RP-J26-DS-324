from pydantic import BaseModel, Field


class StartSessionRequest(BaseModel):
    study_id: str = "pilot_v1"


class ResponseRequest(BaseModel):
    trial_id: int
    issue_type: str
    quality_rating: int = Field(ge=1, le=5)
    comment: str = ""
    play_count: int = Field(ge=0)
    started_at: str