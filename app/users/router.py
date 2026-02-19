from fastapi import APIRouter, Depends, HTTPException, status # ✅ status 추가!
from sqlalchemy.orm import Session
from app.core.database import get_db
from . import models, schemas # UserCreate 같은 규격은 schemas.py에 두는 게 정석이에요!
from datetime import datetime, timedelta
from jose import jwt
from app.core.config import settings
from fastapi.security import OAuth2PasswordBearer
from fastapi.security import OAuth2PasswordRequestForm # ✅ 상단에 추가
from jose import JWTError, jwt
from fastapi.security import APIKeyHeader # OAuth2PasswordBearer 대신 이걸 사용합니다.


router = APIRouter(
    prefix="/api",
    tags=["유저 관리"]
)

# 2. 인증 방식 설정 변경
# name="Authorization"으로 설정하면 스웨거에서 'Authorization'이라는 이름의 칸이 생깁니다.
api_key_header = APIKeyHeader(name="Authorization")

# 회원가입 API
@router.post("/auth/signup")
def signup(user: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="이미 존재하는 이메일입니다.")
    
    new_user = models.User(
        email=user.email,
        hashed_password=user.password, 
        name=user.name
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    # 이메일, 아이디, 이름을 반환합니다.
    return {
        "status": "success", 
        "user_id": new_user.id,
        "email": new_user.email,
        "name": new_user.name
    }

# 💡 1. 토큰 생성 함수 추가 (이게 있어야 로그인이 돌아가요!)
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


# 1. 토큰을 어디서 가져올지 설정 (스웨거 우측 상단 Authorize 버튼 활성화용)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# 3. 유저 확인 함수 수정
def get_current_user(token: str = Depends(api_key_header), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증 정보가 유효하지 않습니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # 💡 보통 스웨거에 "Bearer 토큰값"이라고 넣으므로 Bearer 글자를 떼주는 로직 추가
        if token.startswith("Bearer "):
            token = token.replace("Bearer ", "")
            
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        raise credentials_exception
    return user

# 로그인 API 수정
@router.post("/auth/login")
def login(user_data: schemas.UserLogin, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == user_data.email).first()
    
    # 💡 비밀번호 비교 (나중에 암호화 로직 넣기 전까지는 평문 비교)
    if not user or user.hashed_password != user_data.password:
        raise HTTPException(status_code=401, detail="로그인 정보가 올바르지 않습니다.")
    
    # ✅ 여기서 토큰을 만들어 줍니다!
    access_token = create_access_token(data={"sub": user.email})
    
    return {
        "status": "success",
        "access_token": access_token,
        "token_type": "bearer"
    }
    
# [GET] 기본 프로필 (이름, 이미지 인덱스만)
@router.get("/profile", response_model=schemas.ProfileRead)
def get_my_profile(current_user: models.User = Depends(get_current_user)):
    return current_user

# ✅ [GET] 페르소나 상세 정보 (SBTI 결과만)
@router.get("/profile/persona", response_model=schemas.PersonaRead)
def get_my_persona(current_user: models.User = Depends(get_current_user)):
    if not current_user.persona:
        return {"persona": None}
    
    try:
        # DB의 JSON 문자열을 딕셔너리로 변환하여 전송
        persona_data = json.loads(current_user.persona)
        return {"persona": persona_data}
    except Exception:
        return {"persona": None}

@router.patch("/setting/profile")
def update_profile(
    data: schemas.ProfileUpdate, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # 1. 이름이 들어왔다면 업데이트
    if data.name is not None:
        current_user.name = data.name
    
    # 2. 이미지 인덱스가 들어왔다면 업데이트
    if data.profile_image_index is not None:
        current_user.profile_image_index = data.profile_image_index
    
    db.commit()
    db.refresh(current_user) # 최신 상태로 새로고침
    
    return {
        "status": "success", 
        "message": "프로필이 업데이트되었습니다.",
        "updated_data": {
            "name": current_user.name,
            "profile_image_index": current_user.profile_image_index
        }
    }

# app/users/router.py
import json

# app/users/router.py

@router.post("/setting/profile/persona")
def update_sbti_complex(
    data: schemas.SbtiFinalResult, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # JSON 문자열로 변환하여 저장
    persona_json = json.dumps(data.model_dump(), ensure_ascii=False)
    current_user.persona = persona_json
    db.commit()
    
    return {
        "status": "success",
        "persona_type": data.persona_type,
        "description": data.description  # 저장된 설명글 확인용
    }