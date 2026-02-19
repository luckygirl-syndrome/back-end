from pydantic import BaseModel, EmailStr
from typing import Optional, Any, Dict

from pydantic import BaseModel, EmailStr
from typing import Optional

from enum import Enum
from typing import List


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

class AxisScore(BaseModel):
    result: str    # "D" 또는 "N"
    score: int     # 3개 질문 중 해당 타입이 선택된 개수 (0~3)

class SbtiFinalResult(BaseModel):
    persona_type: str  # "DSN"
    description: str   # "도파민 중독자"
    # 각 축의 점수만 딱 저장 (9개 질문 결과 요약)
    d_vs_n: AxisScore
    s_vs_a: AxisScore
    m_vs_t: AxisScore 

class PersonaRead(BaseModel):
    persona: Optional[SbtiFinalResult] = None

class ProfileUpdate(BaseModel):
    nickname: Optional[str] = None
    profile_img: Optional[str] = None
    
class ShopName(str, Enum):
    MUSINSA = "무신사"
    ABLY = "에이블리"
    ZIGZAG = "지그재그"

class UserShopsUpdate(BaseModel):
    favorite_shops: List[ShopName]

class ChugumeType(str, Enum):
    MORI = "모리걸"
    DEMURE = "드뮤어"
    GIRLCORE = "걸코어"
    SPORTY = "스포티 글램"

class ChugumeUpdate(BaseModel):
    chugume_type: ChugumeType
