# FA26CMPE165-LikeHomeProj
Repo for CMPE 165 semester project

## Run locally

The project has a FastAPI backend and a Next.js frontend. Use Python 3.10+
or newer for the backend (the team setup currently uses Python 3.13).

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate
python -m pip install -r requirements.txt
```

Create `backend/.env` with your MySQL and API settings, then initialize the
database once:

```bash
mysql -u YOUR_MYSQL_USER -p < database/like_home_database_init.sql
uvicorn app.main:app --reload
```

The API is at http://127.0.0.1:8000 and Swagger is at
http://127.0.0.1:8000/docs. SerpApi hotel searches require `API_KEY`; the
unit tests mock that external service and do not make network calls.

Run backend tests from `backend/`:

```bash
python -m pytest -q
```

### Frontend

In another terminal:

```bash
cd frontend/likehome
npm install
npm run dev
```

Open http://localhost:3000. The available frontend check is:

```bash
npm run lint
```
