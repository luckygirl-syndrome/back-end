from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from .database import get_db

app = FastAPI()

@app.get("/api/health")
def health_check(db: Session = Depends(get_db)):
    try:
        # Evaluate a simple query to check the connection
        db.execute(text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection error: {str(e)}")

@app.get("/api/users")
def get_users(db: Session = Depends(get_db)):
    # Placeholder for fetching users
    return [{"id": 1, "name": "User 1"}]
