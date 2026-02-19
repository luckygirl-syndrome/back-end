from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from . import models, schemas
from datetime import datetime, timedelta
from jose import jwt, JWTError
from app.core.config import settings
from fastapi.security import APIKeyHeader
import json
from app.core.security import create_access_token, decode_access_token

router = APIRouter(prefix="/api", tags=["유저 관리"])
api_key_header = APIKeyHeader(name="Authorization")

# 이 함수는 chat/router.py에서도 불러다 쓸 수 있게 설계
def get_current_user(token: str = Depends(api_key_header), db: Session = Depends(get_db)):
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="인증 실패")
    
    email = payload.get("sub")
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=401, detail="유저 없음")
    return user

@router.post("/auth/signup")
def signup(user: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="이미 존재하는 이메일입니다.")
    
    new_user = models.User(
        email=user.email,
        password=user.password, 
        nickname=user.nickname
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"status": "success", "user_id": new_user.user_id, "email": new_user.email, "nickname": new_user.nickname}

@router.post("/auth/login")
def login(user_data: schemas.UserLogin, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == user_data.email).first()
    if not user or user.password != user_data.password:
        raise HTTPException(status_code=401, detail="로그인 정보가 올바르지 않습니다.")
    
    access_token = create_access_token(data={"sub": user.email})
    return {"status": "success", "access_token": access_token, "token_type": "bearer"}

@router.get("/profile", response_model=schemas.ProfileRead)
def get_my_profile(current_user: models.User = Depends(get_current_user)):
    # 1. 기본 정보 세팅
    profile_data = {
        "nickname": current_user.nickname,
        "profile_img": str(current_user.profile_img) if current_user.profile_img else "1",
        "description": "" # 기본값
    }
    
    # 2. 페르소나 데이터가 있다면 description 추출
    if current_user.persona_type:
        try:
            persona_json = json.loads(current_user.persona_type)
            profile_data["description"] = persona_json.get("description", "")
        except:
            pass
            
    return profile_data

@router.patch("/setting/profile")
def update_profile(data: schemas.ProfileUpdate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if data.nickname is not None: current_user.nickname = data.nickname
    if data.profile_img is not None: current_user.profile_img = data.profile_img
    db.commit()
    db.refresh(current_user)
    return {"status": "success", "updated_data": {"nickname": current_user.nickname, "profile_img": current_user.profile_img}}

@router.get("/profile/persona", response_model=schemas.PersonaRead)
def get_my_persona(current_user: models.User = Depends(get_current_user)):
    if not current_user.persona_type: return {"persona": None}
    try:
        return {"persona": json.loads(current_user.persona_type)}
    except: return {"persona": None}

@router.post("/setting/profile/persona")
def update_sbti_complex(data: schemas.SbtiFinalResult, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    current_user.persona_type = json.dumps(data.model_dump(), ensure_ascii=False)
    db.commit()
    return {"status": "success", "persona_type": data.persona_type}