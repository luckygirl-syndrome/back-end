from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from .config import Config

# SSL context is handled by the connection string parameters in Config for pymysql
# But for TiDB Cloud, ensuring SSL is recommended.
# Note: The path /etc/ssl/cert.pem is standard on some Linux distros. 
# On Mac/Windows or if using a specific CA bundle provided by TiDB, adjust accordingly.
# For simplicity, we might default to standard system CA bundle or allow insecure for dev if explicitly requested (not recommended).

engine = create_engine(
    Config.SQLALCHEMY_DATABASE_URI,
    connect_args={
        "ssl": {
            # "ca": "/path/to/ca-bundle.crt" # If needed
        }
    }
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
