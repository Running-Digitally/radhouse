"""Owner presentation choices, independent from agent behavior or authority."""
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Annotated, Literal
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from radhouse.domain.tasks import Rejected


PROFILE_SCHEMA = "radhouse.agent-profile.v1"
DEFAULT_PROFILE = {"schema": PROFILE_SCHEMA, "revision": 0, "name": "", "intro": "",
    "theme": "hearthside", "portrait": "ember", "accent": "fern", "surface": "paper",
    "stateMotion": True, "iconMotion": True, "portraitSize": 80}
CATALOG_PATH = Path(__file__).with_name("static") / "agent-profile" / "catalog.json"
CATALOG_ID = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
BIDI_FORMATTING = frozenset(chr(code) for code in (*range(0x202A, 0x202F), *range(0x2066, 0x206A)))


@lru_cache(maxsize=1)
def portrait_themes():
    """Only packaged catalog IDs can become a saved choice or asset name."""
    try:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        themes = {theme["id"] for theme in catalog["themes"]}
        pairs = {profile["id"]: profile["theme"] for profile in catalog["profiles"]}
        if (len(themes) != len(catalog["themes"]) or len(pairs) != len(catalog["profiles"])
                or not themes or not pairs
                or any(type(value) is not str or not CATALOG_ID.fullmatch(value)
                       for value in (*themes, *pairs))
                or any(theme not in themes for theme in pairs.values())
                or pairs.get(DEFAULT_PROFILE["portrait"]) != DEFAULT_PROFILE["theme"]):
            raise ValueError()
    except (OSError, ValueError, TypeError, KeyError):
        raise Rejected("agent_profile_unavailable", 503) from None
    return pairs


class AgentProfileBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_: Literal[PROFILE_SCHEMA] = Field(alias="schema")
    revision: Annotated[int, Field(ge=0, le=2**63 - 2)]
    name: Annotated[str, Field(max_length=32)]
    intro: Annotated[str, Field(max_length=160)]
    theme: Annotated[str, Field(min_length=1, max_length=32)]
    portrait: Annotated[str, Field(min_length=1, max_length=32)]
    accent: Literal["fern", "clay", "tide", "plum"]
    surface: Literal["paper", "night", "system"]
    stateMotion: bool
    iconMotion: bool
    portraitSize: Literal[48, 80, 128] = 80

    @field_validator("portraitSize", mode="before")
    @classmethod
    def pixel_size(cls, value):
        if type(value) is not int:
            raise ValueError("invalid_portrait_size")
        return value

    @field_validator("name", "intro", mode="before")
    @classmethod
    def plain_text(cls, value, info: ValidationInfo):
        if type(value) is str:
            multiline = info.field_name == "intro"
            if multiline:
                value = value.replace("\r\n", "\n").replace("\r", "\n")
            if any((unicodedata.category(char) in {"Cc", "Cs", "Zl", "Zp"}
                    or char in BIDI_FORMATTING) and not (multiline and char == "\n")
                   for char in value):
                raise ValueError("invalid_profile_text")
            return value.strip()
        return value

    @model_validator(mode="after")
    def catalog_choice(self):
        if portrait_themes().get(self.portrait) != self.theme:
            raise ValueError("invalid_profile_character")
        return self

    def presentation(self):
        return self.model_dump(by_alias=True)
