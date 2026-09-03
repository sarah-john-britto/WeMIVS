from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import Column, ForeignKey, Integer, String, create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4
import hashlib

from sqlalchemy import Column, ForeignKey, Integer, String, DateTime, Text, create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

import io
from fastapi.responses import StreamingResponse
import qrcode

# --- JWT settings (replace SECRET_KEY with a real secret before deploying) ---
SECRET_KEY = "CHANGE-ME-TO-A-LONG-RANDOM-SECRET"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
ALLOWED_ROLES = {"user", "lmo", "gatc", "admin"}

# --- Password hashing (bcrypt via passlib) ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Tells FastAPI/OpenAPI to look for "Authorization: Bearer <token>"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# --- Database setup ---
DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()


# --- User account stored in the database ---
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="user", nullable=False)

class Instrument(Base):
    __tablename__ = "instruments"
    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    make = Column(String, nullable=False)
    model = Column(String, nullable=False)
    serial_number = Column(String, nullable=False)
    category = Column(String, nullable=False)  # e.g. "weighing", "measuring"
    manufactured_year = Column(Integer, nullable=True)


class VerificationRequest(Base):
    __tablename__ = "verification_requests"
    id = Column(Integer, primary_key=True, index=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False)
    request_type = Column(String, nullable=False)  # "new" or "re-verification"
    status = Column(String, default="pending", nullable=False)  # pending/scheduled/verified/rejected
    assigned_officer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    scheduled_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class InspectionResult(Base):
    __tablename__ = "inspection_results"
    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("verification_requests.id"), nullable=False)
    officer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    observations = Column(Text, nullable=True)
    measured_values = Column(Text, nullable=True)  # JSON string
    verdict = Column(String, nullable=False)  # "pass" or "fail"
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class Certificate(Base):
    __tablename__ = "certificates"
    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("verification_requests.id"), nullable=False)
    certificate_number = Column(String, unique=True, index=True, nullable=False)
    issued_date = Column(DateTime, nullable=False)
    valid_until = Column(DateTime, nullable=False)
    integrity_hash = Column(String, nullable=False)
    qr_data = Column(String, nullable=False)


# --- Define what an "Application" looks like in the database ---
class Application(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True, index=True)
    owner_name = Column(String)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    instrument_type = Column(String)
    status = Column(String, default="pending")


Base.metadata.create_all(bind=engine)

# create_all() will not add new columns to an already-existing SQLite table,
# so add owner_id if this database was created before that field existed.
with engine.connect() as conn:
    columns = [col["name"] for col in inspect(engine).get_columns("applications")]
    if "owner_id" not in columns:
        conn.execute(text("ALTER TABLE applications ADD COLUMN owner_id INTEGER"))
        conn.commit()


# --- Request / response shapes ---
class InstrumentCreate(BaseModel):
    make: str
    model: str
    serial_number: str
    category: str
    manufactured_year: Optional[int] = None


class InstrumentOut(BaseModel):
    id: int
    owner_id: int
    make: str
    model: str
    serial_number: str
    category: str
    manufactured_year: Optional[int]

    model_config = {"from_attributes": True}


class VerificationRequestCreate(BaseModel):
    instrument_id: int
    request_type: str  # "new" or "re-verification"


class VerificationRequestOut(BaseModel):
    id: int
    instrument_id: int
    request_type: str
    status: str
    assigned_officer_id: Optional[int]
    scheduled_date: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    role: Optional[str] = "user"


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    role: str

    model_config = {"from_attributes": True}


class LoginRequest(BaseModel):
    email: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- Auth helpers ---
def hash_password(plain_password: str) -> str:
    """Hash a plaintext password so it can be stored safely."""
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return True if the plaintext password matches the stored hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Build a signed JWT that expires after ACCESS_TOKEN_EXPIRE_MINUTES."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """Read the Bearer JWT, load the matching user, or raise 401."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == int(user_id)).first()
        if user is None:
            raise credentials_exception
        # Detach so attributes (id, role, etc.) stay readable after the session closes
        db.expunge(user)
        return user
    finally:
        db.close()
def require_role(*roles: str):
    """
    Dependency factory: returns a dependency that only allows through
    users whose role is in `roles`. Usage:

        @app.get("/admin-only")
        def endpoint(current_user: User = Depends(require_role("admin"))):
            ...
    """
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(roles)}",
            )
        return current_user
    return role_checker


# --- The actual app ---
app = FastAPI()


@app.get("/")
def read_root():
    return {"message": "Hello"}


@app.post("/register", response_model=UserOut)
def register(user_in: UserCreate):
    """Create a new user with a hashed password. Never return the password."""
    role = (user_in.role or "user").lower()
    if role not in ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"role must be one of: {', '.join(sorted(ALLOWED_ROLES))}",
        )

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == user_in.email).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

        user = User(
            name=user_in.name,
            email=user_in.email,
            hashed_password=hash_password(user_in.password),
            role=role,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


@app.post("/login", response_model=Token)
def login(credentials: LoginRequest):
    """Check email/password and return a JWT access token if they match."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == credentials.email).first()
        if not user or not verify_password(credentials.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        access_token = create_access_token(data={"sub": str(user.id)})
        return Token(access_token=access_token)
    finally:
        db.close()


@app.post("/instruments", response_model=InstrumentOut)
def create_instrument(
    instrument: InstrumentCreate,
    current_user: User = Depends(get_current_user),
):
    """Create an instrument owned by the currently logged-in user."""
    db = SessionLocal()
    try:
        new_instrument = Instrument(
            owner_id=current_user.id,
            make=instrument.make,
            model=instrument.model,
            serial_number=instrument.serial_number,
            category=instrument.category,
            manufactured_year=instrument.manufactured_year,
        )
        db.add(new_instrument)
        db.commit()
        db.refresh(new_instrument)
        return new_instrument
    finally:
        db.close()


@app.get("/instruments/me", response_model=list[InstrumentOut])
def list_my_instruments(current_user: User = Depends(get_current_user)):
    """List instruments owned by the currently logged-in user."""
    db = SessionLocal()
    try:
        return db.query(Instrument).filter(Instrument.owner_id == current_user.id).all()
    finally:
        db.close()


@app.post("/applications", response_model=VerificationRequestOut)
def create_verification_request(
    request_in: VerificationRequestCreate,
    current_user: User = Depends(get_current_user),
):
    """Create a verification request against an instrument owned by current_user."""
    db = SessionLocal()
    try:
        instrument = db.query(Instrument).filter(
            Instrument.id == request_in.instrument_id
        ).first()
        if instrument is None:
            raise HTTPException(status_code=404, detail="Instrument not found")
        if instrument.owner_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not own this instrument",
            )

        new_request = VerificationRequest(
            instrument_id=instrument.id,
            request_type=request_in.request_type,
            status="pending",
        )
        db.add(new_request)
        db.commit()
        db.refresh(new_request)
        return new_request
    finally:
        db.close()


@app.get("/applications/me", response_model=list[VerificationRequestOut])
def list_my_verification_requests(current_user: User = Depends(get_current_user)):
    """List verification requests belonging to the current user's own instruments."""
    db = SessionLocal()
    try:
        return (
            db.query(VerificationRequest)
            .join(Instrument, VerificationRequest.instrument_id == Instrument.id)
            .filter(Instrument.owner_id == current_user.id)
            .all()
        )
    finally:
        db.close()


@app.get("/applications", response_model=list[VerificationRequestOut])
def list_all_verification_requests(current_user: User = Depends(require_role("admin"))):
    """Admin-only: list every verification request in the system."""
    db = SessionLocal()
    try:
        return db.query(VerificationRequest).all()
    finally:
        db.close()
class AssignOfficerRequest(BaseModel):
    officer_id: int


class ScheduleRequest(BaseModel):
    scheduled_date: datetime


@app.patch("/applications/{request_id}/assign", response_model=VerificationRequestOut)
def assign_officer(
    request_id: int,
    body: AssignOfficerRequest,
    current_user: User = Depends(require_role("admin")),
):
    """Admin-only: assign an officer to a verification request."""
    db = SessionLocal()
    try:
        req = db.query(VerificationRequest).filter(VerificationRequest.id == request_id).first()
        if req is None:
            raise HTTPException(status_code=404, detail="Verification request not found")

        officer = db.query(User).filter(User.id == body.officer_id).first()
        if officer is None:
            raise HTTPException(status_code=404, detail="Officer not found")
        if officer.role not in ("lmo", "gatc"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Assigned user must have role 'lmo' or 'gatc'",
            )

        req.assigned_officer_id = officer.id
        req.status = "scheduled"
        db.commit()
        db.refresh(req)
        return req
    finally:
        db.close()


@app.patch("/applications/{request_id}/schedule", response_model=VerificationRequestOut)
def schedule_inspection(
    request_id: int,
    body: ScheduleRequest,
    current_user: User = Depends(get_current_user),
):
    """Restricted to the officer assigned to this request; sets the scheduled date."""
    db = SessionLocal()
    try:
        req = db.query(VerificationRequest).filter(VerificationRequest.id == request_id).first()
        if req is None:
            raise HTTPException(status_code=404, detail="Verification request not found")
        if req.assigned_officer_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not the officer assigned to this request",
            )

        req.scheduled_date = body.scheduled_date
        db.commit()
        db.refresh(req)
        return req
    finally:
        db.close()
class InspectionCreate(BaseModel):
    observations: Optional[str] = None
    measured_values: Optional[str] = None  # JSON string
    verdict: str  # "pass" or "fail"


class InspectionOut(BaseModel):
    id: int
    request_id: int
    officer_id: int
    observations: Optional[str]
    measured_values: Optional[str]
    verdict: str
    created_at: datetime

    model_config = {"from_attributes": True}

class CertificateOut(BaseModel):
    id: int
    request_id: int
    certificate_number: str
    issued_date: datetime
    valid_until: datetime
    qr_data: str

    model_config = {"from_attributes": True}


def generate_certificate(db, request_id: int, instrument_id: int) -> Certificate:
    """Create and persist a Certificate for a newly-verified request."""
    certificate_number = str(uuid4())
    issued_date = datetime.now(timezone.utc)
    valid_until = issued_date + timedelta(days=365)

    hash_input = f"{certificate_number}{instrument_id}{issued_date.isoformat()}"
    integrity_hash = hashlib.sha256(hash_input.encode()).hexdigest()

    qr_data = f"https://yourdomain/verify/{certificate_number}"

    certificate = Certificate(
        request_id=request_id,
        certificate_number=certificate_number,
        issued_date=issued_date,
        valid_until=valid_until,
        integrity_hash=integrity_hash,
        qr_data=qr_data,
    )
    db.add(certificate)
    db.commit()
    db.refresh(certificate)
    return certificate


@app.post("/applications/{request_id}/inspect", response_model=InspectionOut)
def submit_inspection(
    request_id: int,
    inspection: InspectionCreate,
    current_user: User = Depends(require_role("lmo", "gatc")),
):
    """Restricted to the officer assigned to this request. Records the inspection
    result and updates the request's status based on the verdict."""
    if inspection.verdict not in ("pass", "fail"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="verdict must be 'pass' or 'fail'",
        )

    db = SessionLocal()
    try:
        req = db.query(VerificationRequest).filter(VerificationRequest.id == request_id).first()
        if req is None:
            raise HTTPException(status_code=404, detail="Verification request not found")
        if req.assigned_officer_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not the officer assigned to this request",
            )

        result = InspectionResult(
            request_id=req.id,
            officer_id=current_user.id,
            observations=inspection.observations,
            measured_values=inspection.measured_values,
            verdict=inspection.verdict,
        )
        db.add(result)

        req.status = "verified" if inspection.verdict == "pass" else "rejected"
        db.commit()
        db.refresh(result)

        if req.status == "verified":
            generate_certificate(db, request_id=req.id, instrument_id=req.instrument_id)

        return result
    finally:
        db.close()

@app.get("/certificates/{certificate_number}", response_model=CertificateOut)
def get_certificate(certificate_number: str, current_user: User = Depends(get_current_user)):
    """Return certificate + instrument + verification details."""
    db = SessionLocal()
    try:
        cert = db.query(Certificate).filter(
            Certificate.certificate_number == certificate_number
        ).first()
        if cert is None:
            raise HTTPException(status_code=404, detail="Certificate not found")
        return cert
    finally:
        db.close()


@app.get("/certificates/{certificate_number}/qr")
def get_certificate_qr(certificate_number: str):
    """Generate and return a QR code PNG for this certificate's verification URL."""
    db = SessionLocal()
    try:
        cert = db.query(Certificate).filter(
            Certificate.certificate_number == certificate_number
        ).first()
        if cert is None:
            raise HTTPException(status_code=404, detail="Certificate not found")

        img = qrcode.make(cert.qr_data)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return StreamingResponse(buf, media_type="image/png")
    finally:
        db.close()

class PublicVerificationOut(BaseModel):
    make: str
    model: str
    serial_number: str
    issued_date: datetime
    valid_until: datetime
    is_valid: bool
    tampered: bool


@app.get("/verify/{certificate_number}", response_model=PublicVerificationOut)
def public_verify(certificate_number: str):
    """Public, no-auth lookup: confirms a certificate's validity and detects tampering."""
    db = SessionLocal()
    try:
        cert = db.query(Certificate).filter(
            Certificate.certificate_number == certificate_number
        ).first()
        if cert is None:
            raise HTTPException(status_code=404, detail="Certificate not found")

        req = db.query(VerificationRequest).filter(
            VerificationRequest.id == cert.request_id
        ).first()
        if req is None:
            raise HTTPException(status_code=404, detail="Associated verification request not found")

        instrument = db.query(Instrument).filter(Instrument.id == req.instrument_id).first()
        if instrument is None:
            raise HTTPException(status_code=404, detail="Associated instrument not found")

        # Recompute the hash the same way generate_certificate() built it originally
        expected_hash_input = f"{cert.certificate_number}{instrument.id}{cert.issued_date.isoformat()}"
        expected_hash = hashlib.sha256(expected_hash_input.encode()).hexdigest()
        tampered = expected_hash != cert.integrity_hash

        now = datetime.now(timezone.utc)
        valid_until = cert.valid_until
        if valid_until.tzinfo is None:
            valid_until = valid_until.replace(tzinfo=timezone.utc)

        is_valid = (not tampered) and (valid_until > now)

        return PublicVerificationOut(
            make=instrument.make,
            model=instrument.model,
            serial_number=instrument.serial_number,
            issued_date=cert.issued_date,
            valid_until=cert.valid_until,
            is_valid=is_valid,
            tampered=tampered,
        )
    finally:
        db.close()

@app.get("/certificates/expiring", response_model=list[CertificateOut])
def certificates_expiring(
    days: int = 30,
    current_user: User = Depends(require_role("admin", "lmo", "gatc")),
):
    """Return certificates expiring within the given number of days."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=days)

        return (
            db.query(Certificate)
            .filter(Certificate.valid_until > now)
            .filter(Certificate.valid_until <= cutoff)
            .all()
        )
    finally:
        db.close()

class MyDashboardOut(BaseModel):
    instruments: list[InstrumentOut]
    requests: list[VerificationRequestOut]
    certificates: list[CertificateOut]


@app.get("/dashboard/me", response_model=MyDashboardOut)
def dashboard_me(current_user: User = Depends(get_current_user)):
    """For role='user': their instruments, requests, and certificate statuses."""
    db = SessionLocal()
    try:
        instruments = db.query(Instrument).filter(Instrument.owner_id == current_user.id).all()
        instrument_ids = [i.id for i in instruments]

        requests = (
            db.query(VerificationRequest)
            .filter(VerificationRequest.instrument_id.in_(instrument_ids))
            .all()
        ) if instrument_ids else []

        request_ids = [r.id for r in requests]
        certificates = (
            db.query(Certificate)
            .filter(Certificate.request_id.in_(request_ids))
            .all()
        ) if request_ids else []

        return MyDashboardOut(instruments=instruments, requests=requests, certificates=certificates)
    finally:
        db.close()


@app.get("/dashboard/officer", response_model=list[VerificationRequestOut])
def dashboard_officer(current_user: User = Depends(require_role("lmo", "gatc"))):
    """For role='lmo'/'gatc': their assigned pending/scheduled requests."""
    db = SessionLocal()
    try:
        return (
            db.query(VerificationRequest)
            .filter(VerificationRequest.assigned_officer_id == current_user.id)
            .filter(VerificationRequest.status.in_(["pending", "scheduled"]))
            .all()
        )
    finally:
        db.close()


class StatusCount(BaseModel):
    status: str
    count: int


class AdminDashboardOut(BaseModel):
    requests_by_status: list[StatusCount]
    certificates_expiring_soon: int


@app.get("/dashboard/admin", response_model=AdminDashboardOut)
def dashboard_admin(current_user: User = Depends(require_role("admin"))):
    """Admin-only: counts of requests grouped by status, and certs expiring in 30 days."""
    db = SessionLocal()
    try:
        from sqlalchemy import func

        status_rows = (
            db.query(VerificationRequest.status, func.count(VerificationRequest.id))
            .group_by(VerificationRequest.status)
            .all()
        )
        requests_by_status = [StatusCount(status=s, count=c) for s, c in status_rows]

        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=30)
        expiring_count = (
            db.query(Certificate)
            .filter(Certificate.valid_until > now)
            .filter(Certificate.valid_until <= cutoff)
            .count()
        )

        return AdminDashboardOut(
            requests_by_status=requests_by_status,
            certificates_expiring_soon=expiring_count,
        )
    finally:
        db.close()