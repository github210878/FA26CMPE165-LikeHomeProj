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
