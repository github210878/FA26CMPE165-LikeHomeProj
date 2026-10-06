# Like Home Backend

### Set up env

1. Python version: 3.13.13

2. install dependencies (including pytest):
   1. go to /backend/
   2. bash: `pip install -r requirements.txt`.

### Run tests

From `backend/`, run `python -m pytest -q`. The tests mock MySQL and SerpApi,
so they do not require a running database or a real API key.

3. init database:
   1. download and install MySQL.
   2. go to /backend/
   3. bash: `mysql -u -p < database/like_home_database_init.sql`

4. enviroment setting:
   1. go to /backend/
   2. create local enviroment setting file `touch .env`
   3. write following to that `.env` file:

```text
DB_HOST=localhost
DB_PORT=3306
DB_NAME=likehome_db
DB_USER=(your mysql username)
DB_PASSWORD=(your mysql password)

EXTERNAL_API_URL=https://serpapi.com/search?engine=google_hotels
API_KEY= (register your own api key)

JWT_SECRET_KEY=your-very-long-random-secret-key
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60
```

5. run backend server:
   1. go to /backend/
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

### Hotel database upgrade

Databases created before the hotel token/cache/partner schema change need the
one-time `database/migrations/002_add_hotel_tokens_cache_and_partners.sql`
migration. A fresh database created from `database/like_home_database_init.sql`
already has these objects and must not run this migration. Back up an existing
database before applying it; MySQL DDL commits implicitly. Apply the earlier
session-version migration separately if that column is also missing.

The migration preserves existing Hotel rows and assigns each one an internal
`legacy:<hotel_id>` token. Such tokens are not SerpApi property tokens and must
not be used to verify property identity or pricing. A real SerpApi property
token identifies one Hotel row uniquely. Partner-created hotels without a
SerpApi identity receive an internal `partner:<uuid>` token. The booking create
request now requires a real property token; cached nightly prices remain
search display data, not an authoritative booking rate.

JWTs now carry a signed account `type` (`user` or `partner`). Tokens issued
before this change have no type and are rejected; signed-in users and partners
must sign in again after deployment. Login response fields and the Bearer
header contract are unchanged.

### Booking creation contract

`POST /bookings/create` requires a user Bearer token. The request supplies a
hotel property token, hotel/room descriptions, stay dates, and a nightly price;
the authenticated user ID is supplied by the server. Check-out must follow
check-in. The server calculates nights and rounds monetary amounts to cents.
New bookings also require one primary guest's full name and contact email.
These fields describe the stay contact and do not change the authenticated
reservation owner or the trusted rate. The owner-only booking-detail endpoint
returns both fields; the My Bookings list does not include them.
Existing databases need `database/migrations/003_add_reservation_guest_information.sql`
after the applicable `001` and `002` migrations. New guest columns remain NULL
for historical reservations; no account name or email is inferred for them.
Fresh databases created from `database/like_home_database_init.sql` already
have the columns. Do not run migration 003 on a fresh database.
The reservation total is nightly price times nights times the existing 1.05
service-fee multiplier. The recorded booking Payment amount applies the existing
1.08 tax multiplier to that total. Its initial status is `pending`; creating
this row does not charge a card. Hotel, room, reservation, and payment writes
commit together or roll back together.

Booking creation revalidates the provider quote before its database critical
section. It then starts a fresh transaction, locks the authenticated active
User row, checks that user's non-cancelled reservations for overlapping
half-open stay dates, and writes Hotel, RoomType, Reservation, and Payment in
one commit. Locking the User row serializes same-user attempts even when the
reservation query finds no rows. Overlap retains HTTP 400; rate changes retain
HTTP 409. On MySQL/InnoDB, the waiting request checks overlap after the first
transaction commits. A rare deadlock or lock timeout rolls back the booking
and returns a generic server error; no automatic retry or extra provider call
is made.

The submitted price acknowledgements are compared with a fresh stay-specific
provider quote before the database critical section. Cached search prices are
display-only. Creating the local Payment record is not external payment
processing or supplier reservation fulfillment.

The authenticated `POST /bookings/pay/{payment_id}` route performs the separate
LikeHome demo payment step. It locks the owned reservation and existing booking
Payment, then changes `pending` to `paid` using the persisted amount. A repeated
request returns the already-paid result. It does not contact a payment provider
or SerpApi. `GET /bookings/get-payment-details/{payment_id}` and
`GET /bookings/get-all-payments` return owned payment ID, reservation ID,
amount, type, and status so a pending payment can be resumed after refresh.
The reservation's `confirmed` status means a local reservation exists; the
separate payment status determines whether the LikeHome payment step completed.

### User sign up:

- API: `/user/register`
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
  - max password lenght is 20 chars
  - frontend can store the response data somewhere like the localstorage for feature use, like pass the user_id to the backend for other API calls, e.g. "get my booking" will require the user_id to identify user.
  - frontend should add the behavior enter your password again, and confirm both enters are same.
  - there is no password validation in the backend. Frontend should add the function to check if the password has 2 chars or maybe 3 numbers or something. The backend takes whatever the frontend provides and hash it, then put in the database.

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
  "phone": "ssdfasdf"
}
```

- Note:
  - max pwd len is 20 chars
  - response is same as signup, the frontend business logic can be same. After login, store the response somewhere in browser or menory.
  - frontend can also set a timeout, if the user stays on a page for too long, it may require a login again.

### Change password:

- API: `/users/change-password`
- Request:

```json
{
  "user_id": "xxx",
  "old_password": "xxx",
  "new_password": "xxx"
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

### delete user:

- API : `/users/delete/`
- Request:

```json
{
  "user_id": "xxx",
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
  - backend will have to authen the user again before de-active user.
  - The database will not delete the raw immediately, rather than mark it as "deleted", because we may need the user information for payment history, booking history or something.
