from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.users.router import get_current_user  # 유저 인증 함수 위치 확인 필요
from app.products.parsers.item_parser import extract_features_from_url # 실제 파싱 함수 위치

router = APIRouter(prefix="/api/products", tags=["상품 분석"])

# 💡 모델을 전역 혹은 싱글톤으로 관리하기 위한 설정
# 서버 실행 시 딱 한 번만 로드되도록 서비스 단에서 처리하는 것이 베스트입니다.

@router.get("/parse")
async def parse_product_url(
    url: str, 
    current_user: dict = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    """
    사용자가 입력한 쇼핑몰 URL을 파싱하여 상품 특징(심리 축 포함)을 반환합니다.
    """
    try:
        # 1. 파싱 로직 실행 (전역 모델을 사용하는 구조인지 확인!)
        # extract_features_from_url 내부에서 매번 KeywordAxisInfer()를 생성하지 않게 주의하세요.
        result = extract_features_from_url(url)
        
        # 2. 에러 핸들링 보강
        if not result or result.get("product_name") == "Error":
            # extract_features_from_url에서 에러 시 {"product_name": "Error"}를 반환하므로 체크
            error_detail = result.get("details", "상품 정보를 가져올 수 없는 URL이야.")
            raise HTTPException(status_code=400, detail=f"파싱 실패: {error_detail}")

        if result.get("product_name") == "Unknown":
            raise HTTPException(status_code=400, detail="지원하는 플랫폼이지만 상품명을 찾지 못했어.")

        # 3. 결과 반환
        return {
            "status": "success",
            "data": result
        }

    except HTTPException as he:
        raise he
    except ValueError as ve:
        # 플랫폼 인식 실패 등의 에러
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        # 예상치 못한 시스템 에러 로그 출력
        print(f"CRITICAL ROUTER ERROR: {e}")
        raise HTTPException(status_code=500, detail="서버 내부 오류로 분석을 완료하지 못했어.")