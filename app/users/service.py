from fastapi import FastAPI, Depends, HTTPException, APIRouter
from sqlalchemy.orm import Session
from .database import get_db, engine
from . import models
from pydantic import BaseModel, EmailStr

router = APIRouter(
    prefix="/api/users", # 모든 주소 앞에 자동으로 붙음
    tags=["유저 관리"]     # 스웨거에서 그룹화됨
)

models.Base.metadata.create_all(bind=engine)

app = FastAPI()

# 데이터 규격 정의
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str

# 회원가입 API (TiDB 저장)
@router.post("/signup")
def signup(user: UserCreate, db: Session = Depends(get_db)):
    # 1. 중복 확인
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="이미 존재하는 이메일입니다.")
    
    # 2. 유저 생성 (TiDB에 Insert)
    new_user = models.User(
        email=user.email,
        hashed_password=user.password, # 보안을 위해 나중에 암호화 추가!
        name=user.name
    )
    db.add(new_user)
    db.commit() # 여기서 실제로 클라우드 DB에 반영됩니다.
    db.refresh(new_user)
    return {"status": "success", "user_id": new_user.id}

# 로그인 API
@router.post("/login")
def login(email: str, password: str, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or user.hashed_password != password:
        raise HTTPException(status_code=401, detail="로그인 정보가 올바르지 않습니다.")
    
    return {"status": "success", "user_name": user.name}

app.include_router(router)

@app.get("/api/users")
def get_users(db: Session = Depends(get_db)):
    # Placeholder for fetching users
    return [{"id": 1, "name": "User 1"}]
