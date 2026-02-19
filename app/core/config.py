import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    TIDB_HOST = os.getenv("TIDB_HOST", "gateway01.ap-northeast-1.prod.aws.tidbcloud.com")
    TIDB_PORT = int(os.getenv("TIDB_PORT", 4000))
    TIDB_USER = os.getenv("TIDB_USER", "your_username")
    TIDB_PASSWORD = os.getenv("TIDB_PASSWORD", "your_password")
    TIDB_DB_NAME = os.getenv("TIDB_DB_NAME", "test")
    
    SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{TIDB_USER}:{TIDB_PASSWORD}@{TIDB_HOST}:{TIDB_PORT}/{TIDB_DB_NAME}?ssl_ca=/etc/ssl/cert.pem&ssl_verify_cert=true&ssl_verify_identity=true"
