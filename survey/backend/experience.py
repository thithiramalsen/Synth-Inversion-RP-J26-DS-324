"""Versioned, self-reported experience choices shared by C1 and C4."""
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def experience_options():
    return json.loads((Path(__file__).resolve().parents[1] / 'config/experience_tags_v1.json').read_text(encoding='utf-8'))


class ExperienceSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: Literal['experience_tags_v1']
    tool_ids: list[str] = Field(default_factory=list, max_length=32)
    example_ids: list[str] = Field(default_factory=list, max_length=16)
    tools_other: str = Field(default='', max_length=250)
    example_other: str = Field(default='', max_length=700)

    @model_validator(mode='after')
    def validate_choices(self):
        options = experience_options()
        for ids, choices in ((self.tool_ids, options['tools']), (self.example_ids, options['examples'])):
            allowed = {choice['id'] for choice in choices}
            if len(set(ids)) != len(ids) or not set(ids).issubset(allowed):
                raise ValueError('Select each offered experience tag at most once.')
        self.tools_other = self.tools_other.strip()
        self.example_other = self.example_other.strip()
        if not self.tool_ids and len(self.tools_other) < 2:
            raise ValueError('Select an instrument, vocal activity or tool, or describe another one.')
        if not self.example_ids and len(self.example_other) < 20:
            raise ValueError('Select an example you have done, or describe another example in at least 20 characters.')
        return self


class ExperienceEntry(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tools: str = Field(default='', max_length=1500)
    example: str = Field(default='', max_length=2000)
    experience_selection: ExperienceSelection | None = None

    @model_validator(mode='after')
    def record_experience(self):
        if self.experience_selection is None:
            # Older pages and studies can continue submitting their original text.
            if not 2 <= len(self.tools.strip()) <= 250 or not 20 <= len(self.example.strip()) <= 700:
                raise ValueError('Please describe your relevant tools and a practical experience example.')
            return self
        options = experience_options()
        selected = self.experience_selection
        # Keep structured IDs and comments, plus readable fields for existing exports.
        self.tools = '; '.join([item['label'] for item in options['tools'] if item['id'] in selected.tool_ids]
                               + ([selected.tools_other] if selected.tools_other else []))
        self.example = '; '.join([item['label'] for item in options['examples'] if item['id'] in selected.example_ids]
                                 + ([selected.example_other] if selected.example_other else []))
        return self
