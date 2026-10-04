# WeMInVS: Weighing & Measuring Instrument Verification System

A backend platform for digitally verifying and certifying weighing and measuring instruments under India's **Legal Metrology Act, 2009**. It replaces scattered, paper-based verification with one role-based system that tracks every instrument from application to certification.

> Built as a hackathon-style project. Backend is working; more features are on the roadmap below.

## The problem

Weighing and measuring instruments (shop scales, fuel dispensers, etc.) must be verified and certified by Legal Metrology authorities. Today the process is fragmented across jurisdictions, which makes it slow, hard to audit, and open to duplicate or fraudulent certificates.

## What it does

- **Authentication:** user registration and login with JWT tokens and bcrypt-hashed passwords
- **Role-based access:** separate roles for **User** (instrument owner), **LMO** (Legal Metrology Officer), and **Admin**
- **Application tracking:** instrument applications store owner details, instrument type, and certification status

## Roadmap

- [ ] Anti-duplication check to prevent repeat certifications across jurisdictions
- [ ] Tamper-proof digital certificates with anti-duplicate QR codes
- [ ] Complaint-triggered re-checks
- [ ] Support for Government Approved Test Centres (GATCs)
- [ ] Officer accountability scoring
- [ ] Offline-first field app for inspections

## Tech stack

| Layer | Tools |
|---|---|
| Framework | Python, FastAPI |
| Database / ORM | SQLite, SQLAlchemy |
| Auth | JWT (python-jose), bcrypt (passlib) |

## Getting started

```bash
# 1. Clone the repo
git clone https://github.com/sarah-john-britto/weminvs.git
cd weminvs

# 2. Create a virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the server
uvicorn main:app --reload
```

Then open **http://127.0.0.1:8000/docs** for the interactive API documentation (Swagger UI), where you can register, log in, and try every endpoint.

> Replace `main:app` with your actual entry file and app name if it's different.

## Environment variables

Create a `.env` file (never commit it):

```
SECRET_KEY=your-secret-key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

## Roles

| Role | Can do |
|---|---|
| User | Register, log in, submit and track instrument applications |
| LMO | Review and update the status of applications |
| Admin | Manage users and oversee the system |

## Screenshots

_Add a screenshot of the `/docs` page here._

## Author

**Sarah John Britto**
[LinkedIn](https://linkedin.com/in/sarah-john-britto-03b422336) · [GitHub](https://github.com/sarah-john-britto)
