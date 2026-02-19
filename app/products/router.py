from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.users.router import get_current_user  # 인증된 유저 정보 가져오기
from .parsers.item_parser import extract_features_from_url
import asyncio

router = APIRouter(prefix="/api/products", tags=["상품 분석"])

@router.get("/parse")
async def parse_product_url(
    url: str, 
    current_user: dict = Depends(get_current_user), # 로그인한 유저만 사용 가능
    db: Session = Depends(get_db)
):
    """
    사용자가 입력한 쇼핑몰 URL을 파싱하여 상품 특징(심리 축 포함)을 반환합니다.
    """
    try:
        # 셀레니움은 동기 방식이라 비동기 환경에서 차단되지 않도록 별도 스레드에서 실행하는 것이 정석이지만,
        # 일단 테스트를 위해 직접 호출할게! (언니 설계대로 나중에 service.py로 옮기면 좋아)
        
        # 1. 파싱 로직 실행
        result = extract_features_from_url(url)
        
        if not result or result.get("product_name") == "Unknown":
            raise HTTPException(status_code=400, detail="상품 정보를 가져올 수 없는 URL이야.")

        # 2. 결과 반환 (이 JSON이 나중에 chat logic으로 들어갈 거야)
        return {
            "status": "success",
            "data": result
        }

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        print(f"Error during parsing: {e}")
        raise HTTPException(status_code=500, detail="서버 내부 오류로 파싱에 실패했어.")