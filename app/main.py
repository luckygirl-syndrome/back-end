import redis
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.core.config import settings
from app.core.database import engine, Base, get_db
from app.users.router import router as user_router # 유저 라우터 가져오기
from app.users import models # ✅ 모델을 불러와야 테이블을 만듭니다.
from app.products import router as products_router
from app.chat import router as chat_router
from app.dashboard import home_router
from app.chat.after_chat.router import router as after_chat_router
from fastapi.middleware.cors import CORSMiddleware


# 서버 시작 시 테이블 생성
Base.metadata.create_all(bind=engine)

# [중요] 나중에 각 도메인의 models를 만든 후 여기에 import해야 DB 테이블이 생성됩니다.
# 지금은 에러 방지를 위해 이대로 둡니다.

# 서버 시작 시 테이블 생성 (Base에 연결된 모델들)
Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.PROJECT_NAME)

# CORS 설정 추가
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 테스트용으로 모두 허용, 실제 배포 시에는 프론트 주소만!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ 이 줄이 있어야 스웨거에 '유저 관리' 메뉴가 뜹니다!
app.include_router(user_router)
app.include_router(products_router.router)
app.include_router(chat_router.router) # 챗봇 라우터도 포함시킵니다.
app.include_router(after_chat_router) # 채팅 후 API 포함
# `app.include_router(home_router.router)` is including the routes defined in the `home_router` router
# into the FastAPI application `app`. This allows the endpoints defined in the `home_router` to be
# accessible and handled by the FastAPI application when it is running. This line of code ensures that
# the routes defined in the `home_router` are registered and available for use within the FastAPI
# application.
app.include_router(home_router.router)

@app.get("/")
def root():
    return {"message": f"Welcome to {settings.PROJECT_NAME} API"}

# 헬스체크 API (DB + Redis)
@app.get("/api/health")
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection error: {str(e)}")

    try:
        r = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=0)
        r.ping()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redis connection error: {str(e)}")

    return {"status": "ok", "db": "connected", "redis": "connected"}