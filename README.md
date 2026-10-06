# FA26CMPE165-LikeHomeProj
Repo for CMPE 165 semester project

## Run locally

The project has a FastAPI backend and a Next.js frontend. Use Python 3.10+
or newer for the backend (the team setup currently uses Python 3.13).

# Like Home Backend

### Set up env

1. Python version: 3.13.13

2. install dependencies (including pytest):
   1. go to backend/
   2. bash: `pip install -r requirements.txt`.

### Run tests

From `backend/`, run `python -m pytest -q`. The tests mock MySQL and SerpApi,
so they do not require a running database or a real API key.

3. init database:
   1. download and install MySQL.
   2. go to backend/
   3. bash: `mysql -u -p < database/like_home_database_init.sql`

4. enviroment setting:
   1. go to backend/
   2. create local enviroment setting file `touch .env`
   3. write following to that `.env` file:

```text
DB_HOST=localhost
DB_PORT=3306
DB_NAME=likehome_db
DB_USER=(your mysql username)
DB_PASSWORD=(your mysql password)

EXTERNAL_API_URL=  hold on
API_KEY= hold on

JWT_SECRET_KEY=your-very-long-random-secret-key
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60
ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

For an existing database, run the one-time migration after pulling this
change:

```bash
mysql -u YOUR_MYSQL_USER -p likehome_db < database/migrations/001_add_session_version.sql
```

Never commit a real `.env` file or a real JWT secret.

5. run backend server:
   1. go to backend/
   2. bash: `uvicorn app.main:app --reload`
   3. you can see something like:

```text
(fastapi-env) jesse@Jesses-MacBook-Pro backend % uvicorn app.main:app --reload
INFO:     Will watch for changes in these directories: ['/Users/jesse/Project/FA26CMPE165-LikeHomeProj/backend']
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [73938] using StatReload
INFO:     Started server process [73940]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

6. user Swagger to test API endpoints:
   1. open your browser, enter `http://127.0.0.1:8000/docs`
   2. there is one `users/register` api i made. you can try to create a new user to your database to see if db and backend server are working good.

### Backend structure:

```text

backend/
├── app/
│   ├── __init__.py
│   ├── main.py
│   │
│   ├── config/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   └── database.py
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── (data models)
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── user_schema.py
│   │   ├── (schemas to frontend, like response/request)
│   │
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── user_dao.py
│   │   ├── (here for database access objects)
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── user_service.py
│   │   ├── (this is for business logics)
│   │
│   ├── utilities/
│   │   ├── __init__.py
│   │   ├── (this is for tools)
│   │
│   └── routers/
│       ├── __init__.py
│       ├──  user_router.py
|       ├──  (this package is for defining API endpoints)
│
├── .env
├── requirements.txt
└── README.md
```

### Note:

- The workflow is pretty much:  
   For write `frontend -(data schema)-> router --> service -(data model)-> dao --> db`
  For read `db --> dao -(data model)-> --> service --> router -(data schema)-> frontend`

- `schema` is for passing data between frontend and backend,
  `request` is `frontend --> router` and `response` is `router --> frontend`

- `model` is for pass data from `DAO` to `database`. we can add behaviors to the model as well.

- `__inti__.py` is package marking file. the fastAPI will know here is a package if you have this empty file in the folder.

---

# API endpoints:

### Hotel search:

- API: `GET /hotels/search` with `q`, `check_in_date`, and `check_out_date` query parameters.
- Each result in `properties` includes LikeHome search fields: `name`,
  `price_per_night`, `rating`, `amenities`, and `property_token`.
- `price_per_night` is the numeric `rate_per_night.extracted_lowest` value from
  SerpApi in the requested currency. `rating` comes from `overall_rating`.
  Missing or malformed values are returned as `null`.
- Search results are returned directly to the client and are not stored in MySQL.
  Existing SerpApi-shaped result fields remain available for current clients.
- Dates must be real calendar dates in `YYYY-MM-DD` format. Check-in may be
  today (using the backend server's local date) or later; check-out must be
  strictly after check-in. Guest counts must be whole numbers: adults 1-20,
  children 0-20. Invalid inputs return HTTP 422 with the field and reason,
  before any SerpApi request is made.

Run backend tests with `python -m pytest -q -p no:cacheprovider tests`.

### User sign up:

- API: `POST /users/register`
- Request data schema:

```json
{
  "email": "xxxxxx",
  "password": "xxxxxx",
  "full_name": "john smith",
  "phone": "544-646-6464"
}
```

- Response data schema:

```json
{
  "user_id": "1234",
  "email": "xxxx",
  "full_name": "sdfsdf",
  "phone": "ssdfasdf"
}
```

- Note:
  - passwords must be 8-20 characters and are hashed before storage.
  - registration does not create a session; the client must log in afterward.

### user log in:

- API: `/users/login`
- Request data schema:

```json
{
  "email": "xxx",
  "password": "xxx"
}
```

- Response data schema:

```json
{
  "user_id": "1234",
  "email": "xxxx",
  "full_name": "sdfsdf",
  "phone": "ssdfasdf",
  "access_token": "jwt-token",
  "token_type": "bearer"
}
```

- Note:
  - send the token on protected requests as `Authorization: Bearer <access_token>`.
  - tokens expire after `JWT_EXPIRE_MINUTES`.
  - the backend also checks that the account is still active and that the token's
    session version matches the database.

### Current user:

- API: `GET /users/me`
- Requires a bearer token.
- Returns the authenticated user's ID. Deleted users and invalidated sessions
  receive HTTP 401.

### Logout:

- API: `POST /users/logout`
- Requires a bearer token.
- Invalidates all currently issued access tokens for that user by advancing the
  session version.

### Change password:

- API: `/users/change-password`
- Request:

```json
{
  "old_password": "xxx",
  "new_password": "xxx"
}
```

- Response:
  - For success

```json
{
   "status": True,
   "message": "Password changed successfully"
}
```

- fault:
- HTTPException

### Delete user:

- API: `DELETE /users/delete`
- Request:

```json
{
  "password": "xxx"
}
```

- Response:
  - For success

```json
{
   "status": True,
   "message": "User deleted successfully"
}
```

- fault:
- HTTPException

- Note:
  - the authenticated user is identified from the JWT, not from the request body.
  - the database keeps the row for booking and payment history, but marks the
    account as `deleted`.
  - deleting the account invalidates previously issued access tokens.

### Authorization rules:

- Protected routes reject missing, invalid, expired, deleted, and invalidated
  sessions with HTTP 401.
- Password changes and account deletion can only affect the user represented by
  the bearer token.
- Booking and payment detail/cancellation routes filter by both the requested
  record ID and the authenticated user's ID.
- `POST /bookings/cancel-booking/{reservation_id}` returns HTTP 404 for a missing
  or non-owned reservation, HTTP 409 for an already cancelled/completed booking
  or ambiguous payment records, and HTTP 500 without database details if the
  transaction fails. A successful response includes `reservation_id`, `status`,
  `booking_payment_id`, `booking_payment_status`, `cancellation_payment_id`,
  `cancellation_amount`, and `cancellation_payment_status`.
- Booking creation records a pending booking Payment. The authenticated
  `POST /bookings/pay/{payment_id}` operation marks an owned pending booking
  Payment paid in LikeHome, using its persisted amount. Repeated Pay returns
  the already-paid result. This is an application-level demo payment; no card,
  bank, or external provider is charged. Checkout opens a payment review page,
  and confirmation displays persisted payment state only after payment.
- Cancellation creates a pending cancellation Payment equal to 20% of the
  reservation total. That percentage is the team's current implementation
  policy (`CANCELLATION_FEE`), not a percentage specified by the course
  requirement. A paid booking Payment becomes `refunded` in LikeHome's ledger;
  an unpaid booking Payment stays `pending` but cannot be paid after the
  reservation is cancelled. No external charge or refund is processed.


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
