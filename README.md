# Tender Guardian

Backend-only Django + DRF project for public tender management with built-in corruption risk detection.

## Overview
Tender Guardian is a role-based procurement backend that supports:

- admin and company authentication
- tender creation and management
- company bid/application submission
- automatic corruption risk analysis
- risk flags, risk scores, and risk statistics
- Swagger/OpenAPI documentation

The project is designed to support a frontend tender platform where:
- admins publish and monitor tenders
- companies log in and submit bids
- suspicious tenders are flagged as `LOW`, `MEDIUM`, or `HIGH` risk

## Main Features
- Django + Django REST Framework backend
- PostgreSQL-ready configuration via environment variables
- Docker and Docker Compose support
- Token-based authentication
- Tender CRUD APIs
- Application/Bid APIs
- Risk scoring engine
- Optional Gemini AI summary support
- Unfold-based Django admin
- Swagger UI via `drf-spectacular`

## Tech Stack
- Python
- Django
- Django REST Framework
- PostgreSQL
- Docker / Docker Compose
- drf-spectacular (Swagger / OpenAPI)
- Unfold admin
- Optional Google Gemini integration

## Project Structure
```text
TenderAiAntiCorruption/
├── TenderAiAntiCorruption/      # Django project config
├── tenders/                     # Main app
│   ├── management/commands/     # Seed command
│   ├── migrations/              # DB migrations
│   ├── services/                # Risk scoring + AI summary services
│   ├── admin.py
│   ├── models.py
│   ├── serializers.py
│   ├── urls.py
│   ├── views.py
│   └── tests.py
├── Dockerfile
├── docker-compose.yml
├── docker-entrypoint.sh
├── requirements.txt
├── workfile.md                  # API contract / integration notes
└── manage.py
```

## Demo Credentials
Seeded by `python manage.py seed_mock_data`

| Login | Password | Role |
|---|---|---|
| `admin` | `admin123` | admin |
| `acme` | `acme123` | company |
| `nova` | `nova123` | company |

## Quick Start
### Option 1: Run with Docker
This is the easiest way to run the project for review.

1. Create the environment file:
```bash
cp .env.example .env
```

2. Start the stack:
```bash
docker compose up --build
```

3. Open:
- API base: `http://localhost:8000`
- Swagger docs: `http://localhost:8000/api/docs/`
- OpenAPI schema: `http://localhost:8000/api/schema/`
- Django admin: `http://localhost:8000/admin/`

Notes:
- migrations run automatically on container startup
- mock data can be seeded automatically in Docker because `SEED_MOCK_DATA` is enabled in compose

### Option 2: Run Locally
#### 1. Create and activate a virtual environment
```bash
python -m venv venv
source venv/bin/activate
```

#### 2. Install dependencies
```bash
pip install -r requirements.txt
```

#### 3. Create environment file
```bash
cp .env.example .env
```

#### 4. Make sure PostgreSQL is running
By default the project expects:
```env
POSTGRES_DB=tender_guardian
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
```

Adjust `.env` if your PostgreSQL setup is different.

#### 5. Run migrations
```bash
python manage.py migrate
```

#### 6. Seed demo data
```bash
python manage.py seed_mock_data
```

#### 7. Start the server
```bash
python manage.py runserver
```

Open:
- API: `http://127.0.0.1:8000`
- Swagger docs: `http://127.0.0.1:8000/api/docs/`
- Admin: `http://127.0.0.1:8000/admin/`

## Environment Variables
Minimal `.env` example:

```env
DJANGO_SECRET_KEY=change-me-for-local-development
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
DJANGO_DB_ENGINE=django.db.backends.postgresql

POSTGRES_DB=tender_guardian
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_SSLMODE=prefer
POSTGRES_CONN_MAX_AGE=60

SEED_MOCK_DATA=false
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
CORS_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
CORS_ALLOW_CREDENTIALS=True
```

## CORS
The backend is configured to allow frontend requests from:

- `http://localhost:5173`
- `http://127.0.0.1:5173`

Configuration is environment-driven:

```env
CORS_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
CORS_ALLOW_CREDENTIALS=True
```

### Optional SQLite Override for Testing
If PostgreSQL is not available and you only want to run tests or debug locally:

```bash
env DJANGO_DB_ENGINE=django.db.backends.sqlite3 SQLITE_NAME=/tmp/tender_guardian.sqlite3 python manage.py test
```

## Key Endpoints
### Auth
- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/me`

### Tenders
- `GET /tenders`
- `GET /tenders/<tenderId>`
- `POST /tenders`
- `PUT /tenders/<tenderId>`
- `DELETE /tenders/<tenderId>`

### Applications
- `GET /applications`
- `POST /applications`
- `PATCH /applications/<applicationId>/status`

### Risk
- `POST /risk/analyze/<tenderId>`
- `GET /risk/stats`
- `GET /risk/flags/<tenderId>`

### Users
- `GET /users`
- `POST /users`

For exact request/response shapes, see [workfile.md](./workfile.md).

## Swagger / OpenAPI
Swagger UI is available at:

```text
/api/docs/
```

OpenAPI schema is available at:

```text
/api/schema/
```

## Running Tests
Recommended test command:
```bash
env DJANGO_DB_ENGINE=django.db.backends.sqlite3 SQLITE_NAME=/tmp/tender_guardian_test.sqlite3 python manage.py test
```

System check:
```bash
python manage.py check
```

## Risk Detection Logic
The backend currently analyzes tenders using signals such as:
- price anomaly vs market average
- exact budget match
- budget overrun
- company execution/failure history
- consecutive wins
- winner repetition by organization
- single bidder
- short tender deadline
- late bid submissions
- repeated participants
- very close competing bids
- repeated winner vs same losers

Output includes:
- `riskScore`
- `riskLevel`
- `riskFlags`

Optional AI-generated summary is available if `GEMINI_API_KEY` is configured.

## Examiner Notes
If you want the fastest review path:

1. Run with Docker:
```bash
cp .env.example .env
docker compose up --build
```

2. Open Swagger:
```text
http://localhost:8000/api/docs/
```

3. Use seeded credentials:
- `admin / admin123`
- `acme / acme123`
- `nova / nova123`

## Current Scope
This repository is backend-only.

It is structured to support a frontend tender platform, but the frontend code is not part of this repository.
