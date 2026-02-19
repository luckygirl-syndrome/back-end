from pydantic import BaseModel, EmailStr
from typing import Optional, Any, Dict

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str
    
# 1. 기본 프로필용 (이름, 이미지)
class ProfileRead(BaseModel):
    name: str
    profile_image_index: int

    class Config:
        from_attributes = True

# 2. 페르소나 전용 (SBTI 결과)
class PersonaRead(BaseModel):
    persona: Optional[SbtiFinalResult] = None
    
class Token(BaseModel):
    access_token: str
    token_type: str

# 토큰 안에 들어있을 내용 (나중에 확장용)
class TokenData(BaseModel):
    email: Optional[str] = None
    
class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    profile_image_index: Optional[int] = None
    

class AxisDetail(BaseModel):
    result: str
    # 해당 축에 필요한 카운트만 남기거나, 공통으로 사용합니다.
    count_1: int = 0 # 예: D 또는 S 또는 M의 점수
    count_2: int = 0 # 예: N 또는 A 또는 T의 점수
    confidence: float

class SbtiFinalResult(BaseModel):
    persona_type: str
    # 💡 Dict 대신 명확한 필드명으로 정의하여 additionalProp을 제거합니다.
    d_vs_n: AxisDetail
    s_vs_a: AxisDetail
    m_vs_t: AxisDetail
    description: str     # 유저에게 보여줄 성향 설명 문구