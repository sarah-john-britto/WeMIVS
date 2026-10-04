# WeMIVS

WeMIVS: Weighing & Measuring Instrument Verification System

A backend platform for digitally verifying and certifying weighing and measuring instruments under India's Legal Metrology Act, 2009. It replaces scattered, paper-based verification with one role-based system that tracks every instrument from application to certification.

The problem

Weighing and measuring instruments (shop scales, fuel dispensers, etc.) must be verified and certified by Legal Metrology authorities. Today the process is fragmented across jurisdictions, which makes it slow, hard to audit, and open to duplicate or fraudulent certificates.

What it does
Authentication: user registration and login with JWT tokens and bcrypt-hashed passwords
Role-based access: separate roles for User (instrument owner), LMO (Legal Metrology Officer), and Admin
Application tracking: instrument applications store owner details, instrument type, and certification status
