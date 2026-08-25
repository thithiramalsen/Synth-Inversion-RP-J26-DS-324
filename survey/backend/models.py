from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


StudyId = Literal["pilot_quality", "c1_descriptors", "c4_triplets", "pilot_v1"]


class StartSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study_id: StudyId = "pilot_quality"


class ResponseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trial_id: str = Field(min_length=1, max_length=128)
    answers: dict[str, Any]
    play_counts: dict[str, int]
    started_at: datetime


class PilotQualityAnswers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_type: Literal["none", "silence", "click_pop", "clipping", "pitch", "other"]
    quality_rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=1000)


class C1DescriptorAnswers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dark_bright: int = Field(ge=1, le=7)
    smooth_rough: int = Field(ge=1, le=7)
    thin_warm: int = Field(ge=1, le=7)
    short_sustained: int = Field(ge=1, le=7)
    comment: str = Field(default="", max_length=1000)


class C4TripletAnswers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    choice: Literal["candidate_a", "candidate_b"]
    confidence: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=1000)


class SingleAudioPlayCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample: int = Field(ge=1)


class C4AudioPlayCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference: int = Field(ge=1)
    candidate_a: int = Field(ge=1)
    candidate_b: int = Field(ge=1)
