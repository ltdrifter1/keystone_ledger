from pydantic import BaseModel, Field


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    initials: str
    role: str


class SessionOut(BaseModel):
    user: UserOut
    users: list[UserOut] = Field(default_factory=list)


class SessionSwitch(BaseModel):
    username: str
