from pydantic import BaseModel, Field, field_validator


class DeadLetterRequeueRequest(BaseModel):
    acknowledgment: str = Field(min_length=1, max_length=240)

    @field_validator("acknowledgment")
    @classmethod
    def normalize_acknowledgment(cls, value: str) -> str:
        return " ".join(value.strip().split())


class DeadLetterResolveRequest(BaseModel):
    acknowledgment: str = Field(min_length=1, max_length=240)
    note: str = Field(min_length=1, max_length=1000)

    @field_validator("acknowledgment", "note")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return " ".join(value.strip().split())
