from pydantic import BaseModel, Field

class SurveyRequest(BaseModel):
    q1: int = Field(..., description="장바구니 기간 (1-5)", example=1)
    q2: int = Field(..., description="연락 이유 (1-4)", example=3)
    q3: int = Field(..., description="구매 확신도 (1-4)", example=2)
    qc: int = Field(..., description="핵심 매력 (1-7)", example=6)