from pydantic import BaseModel, EmailStr
from typing import Optional, Any, Dict

from pydantic import BaseModel, EmailStr
from typing import Optional

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    nickname: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class ProfileRead(BaseModel):
    nickname: str
    profile_img: Optional[str] = "1"
    description: Optional[str] = None  # 성향 설명 필드 추가

    class Config:
        from_attributes = True

class AxisDetail(BaseModel):
    result: str
    count_1: int = 0 
    count_2: int = 0 
    confidence: float

class SbtiFinalResult(BaseModel):
    persona_type: str
    d_vs_n: AxisDetail
    s_vs_a: AxisDetail
    m_vs_t: AxisDetail
    description: str     

class PersonaRead(BaseModel):
    persona: Optional[SbtiFinalResult] = None

class ProfileUpdate(BaseModel):
    nickname: Optional[str] = None
    profile_img: Optional[str] = None