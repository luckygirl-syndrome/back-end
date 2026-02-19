from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.core.config import settings
from app.core.database import engine, Base, get_db
from app.users.router import router as user_router # 유저 라우터 가져오기
from app.users import models # ✅ 모델을 불러와야 테이블을 만듭니다.

# 서버 시작 시 테이블 생성
Base.metadata.create_all(bind=engine)

# [중요] 나중에 각 도메인의 models를 만든 후 여기에 import해야 DB 테이블이 생성됩니다.
# 지금은 에러 방지를 위해 이대로 둡니다.

# 서버 시작 시 테이블 생성 (Base에 연결된 모델들)
Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.PROJECT_NAME)

# ✅ 이 줄이 있어야 스웨거에 '유저 관리' 메뉴가 뜹니다!
app.include_router(user_router)

@app.get("/")
def root():
    return {"message": f"Welcome to {settings.PROJECT_NAME} API"}

# 우리가 아까 만든 헬스체크 API
@app.get("/api/health")
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection error: {str(e)}")