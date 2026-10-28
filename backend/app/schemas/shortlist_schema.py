
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ShortlistAddRequest(BaseModel):
    """Request to save a hotel to the user's shortlist."""

    model_config = ConfigDict(extra="forbid")

    property_token: str = Field(min_length=1, max_length=255)

    @field_validator("property_token")
    @classmethod
    def validate_property_token(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("Property token cannot be blank")

        return value


class ShortlistItemResponse(BaseModel):
    """One hotel saved in the user's shortlist."""

    property_token: str


class ShortlistResponse(BaseModel):
    """List of hotels saved by the authenticated user."""

    properties: list[ShortlistItemResponse]
