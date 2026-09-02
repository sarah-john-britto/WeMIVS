from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker

# --- Database setup ---
DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# --- Define what an "Application" looks like in the database ---
class Application(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True, index=True)
    owner_name = Column(String)
    instrument_type = Column(String)
    status = Column(String, default="pending")

Base.metadata.create_all(bind=engine)

# --- Define what data we expect when someone SUBMITS an application ---
class ApplicationCreate(BaseModel):
    owner_name: str
    instrument_type: str

# --- The actual app ---
app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Hello, my backend is working!"}

# --- NEW: Submit a new application ---
@app.post("/applications")
def create_application(application: ApplicationCreate):
    db = SessionLocal()
    new_app = Application(
        owner_name=application.owner_name,
        instrument_type=application.instrument_type,
    )
    db.add(new_app)
    db.commit()
    db.refresh(new_app)
    db.close()
    return new_app

# --- NEW: List all applications ---
@app.get("/applications")
def list_applications():
    db = SessionLocal()
    apps = db.query(Application).all()
    db.close()
    return apps