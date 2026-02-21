from datetime import datetime, timedelta
from jose import jwt
from app.core.config import settings

# 토큰 생성 기계
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

# 토큰 검증 기계
def decode_access_token(token: str):
    try:
        if token.startswith("Bearer "):
            token = token.replace("Bearer ", "")
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except:
        return None