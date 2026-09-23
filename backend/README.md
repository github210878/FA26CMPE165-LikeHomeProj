# Like Home Backend

### Set up env

1. Python version: 3.13.13

2. install dependencies:
   1. go to /backend/
   2. bash: `pip install -r requirements.txt`.

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

EXTERNAL_API_URL=  hold on
API_KEY= hold on
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
  - frontend can also set a timeout, if the user stay on a page for to long, it will require a login again.

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
