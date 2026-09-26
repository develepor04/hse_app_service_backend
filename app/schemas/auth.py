from pydantic import BaseModel
from typing import Optional


class LoginRequest(BaseModel):
    username: str  # accepts username or email
    password: str


class DeleteAccountRequest(BaseModel):
    password: str  # re-confirm identity before a destructive self-delete


class TokenData(BaseModel):
    user_id: int
    username: str
    full_name: Optional[str] = None
    email: str
    role: str
    role_level: int


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: TokenData
    refresh_token: Optional[str] = None
