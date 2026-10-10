"""Opt-in Docker-owned MySQL verification; never accepts a database URL.

Run with backend/.venv/bin/python and --disposable. The normal backend test
suite does not invoke this runner. Credentials exist only in this process and
the new container; no application/environment files are read or changed.
"""

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import uuid

import pymysql
import pytest
from sqlalchemy import URL, create_engine, event

BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
IMAGE = "mysql:5.7.44"
PRE004 = "57088923e952e9c4baba48cc71d2a9f94e4a138e"


def docker(*args, env=None):
    # Pin the local Desktop context rather than relying on a mutable default.
    return subprocess.run(["docker", "--context", "desktop-linux", *args], check=True, capture_output=True,
                          text=True, env=env).stdout.strip()


def rewrite_schema(sql, schema):
    assert re.fullmatch(r"us72_(upgrade|fresh)_[0-9a-f]{12}", schema)
    assert sql.count("USE likehome_db;") == 1
    return sql.replace("CREATE DATABASE IF NOT EXISTS likehome_db;",
                       f"CREATE DATABASE IF NOT EXISTS `{schema}`;").replace(
                           "USE likehome_db;", f"USE `{schema}`;")


def execute_script(connection, sql):
    # Repository DDL has no routines, DELIMITER, or semicolons inside strings.
    sql = re.sub(r"--[^\n]*", "", sql)
    with connection.cursor() as cursor:
        for statement in sql.split(";"):
            if statement.strip():
                cursor.execute(statement)


def snapshot(connection):
    columns = {
        "users": "*", "hotels": "*", "room_types": "*", "payments": "*",
        "reservations": "reservation_id,user_id,room_type_id,guest_full_name,guest_email,"
        "check_in_date,check_out_date,status,total_price,created_at",
    }
    keys = {"users": "user_id", "hotels": "hotel_id", "room_types": "room_type_id",
            "payments": "payment_id", "reservations": "reservation_id"}
    with connection.cursor() as cursor:
        result = {}
        for table, fields in columns.items():
            cursor.execute(f"SELECT {fields} FROM {table} ORDER BY {keys[table]}")
            result[table] = cursor.fetchall()
        return result


class Context:
    def __init__(self, connection_options, upgrade, fresh, server_id):
        self.options = connection_options
        self.upgrade, self.fresh, self.server_id = upgrade, fresh, server_id
        self.evidence = {}
        self.engines = []

    def connect(self, schema=None):
        assert schema in (None, self.upgrade, self.fresh)
        connection = pymysql.connect(**self.options, database=schema)
        with connection.cursor() as cursor:
            cursor.execute("SELECT @@server_id, VERSION()")
            marker, version = cursor.fetchone()
            assert marker == self.server_id and version == "5.7.44", "Wrong disposable server"
            cursor.execute("SET time_zone='+00:00'")
            cursor.execute("SET SESSION innodb_lock_wait_timeout=8")
        connection.commit()
        return connection

    def engine(self, schema):
        assert schema in (self.upgrade, self.fresh)
        engine = create_engine(URL.create(
            "mysql+pymysql", username=self.options["user"], password=self.options["password"],
            host=self.options["host"], port=self.options["port"], database=schema,
        ), hide_parameters=True, pool_size=10, max_overflow=5, pool_pre_ping=True)

        @event.listens_for(engine, "connect")
        def initialize(connection, _):
            with connection.cursor() as cursor:
                cursor.execute("SELECT @@server_id, VERSION(), DATABASE()")
                assert cursor.fetchone() == (self.server_id, "5.7.44", schema)
                cursor.execute("SET time_zone='+00:00'")
                cursor.execute("SET SESSION innodb_lock_wait_timeout=8")
            connection.commit()

        self.engines.append(engine)
        return engine


class Plugin:
    def __init__(self, context):
        self.context = context

    def pytest_configure(self, config):
        config._us72_disposable = self.context

    def pytest_sessionfinish(self, session, exitstatus):
        self.context.evidence["tests_collected"] = session.testscollected
        self.context.evidence["tests_failed"] = session.testsfailed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disposable", action="store_true", required=True)
    parser.add_argument("--evidence", type=Path, required=True,
                        help="JSON findings path (no credentials)")
    args = parser.parse_args()
    os.environ.update({
        "PYTHON_DOTENV_DISABLED": "1", "DB_HOST": "127.0.0.1", "DB_PORT": "1",
        "DB_USER": "us72_disabled", "DB_PASSWORD": "synthetic-unused",
        "DB_NAME": "us72_no_application_database", "API_KEY": "synthetic-unused",
        "EXTERNAL_API_URL": "http://127.0.0.1:1",
        "JWT_SECRET_KEY": "us72-isolated-signing-key-at-least-32-characters",
        "JWT_ALGORITHM": "HS256",
    })
    sys.path.insert(0, str(BACKEND))
    desktop, = json.loads(docker("context", "inspect", "desktop-linux"))
    assert desktop["Endpoints"]["docker"]["Host"].startswith("unix://"), "Require local Desktop socket"
    server = json.loads(docker("version", "--format", "{{json .Server}}"))
    before_containers = set(docker("ps", "-aq").split())
    before_volumes = set(docker("volume", "ls", "-q").split())
    run_id = uuid.uuid4().hex
    name = f"likehome-us72-{run_id}"
    upgrade, fresh = (f"us72_{kind}_{run_id[:12]}" for kind in ("upgrade", "fresh"))
    server_id = secrets.randbelow(2147483646) + 1
    password = secrets.token_urlsafe(32)
    # Connection settings are fixed before startup: new name, tmpfs, no bind
    # mounts/reused volumes, random loopback port, fresh credentials and marker.
    environment = os.environ.copy()
    environment["MYSQL_ROOT_PASSWORD"] = password
    environment["MYSQL_ROOT_HOST"] = "%"
    command = ["run", "-d", "--platform", "linux/amd64", "--name", name,
               "--label", f"likehome.us72.run={run_id}",
               "--publish", "127.0.0.1::3306", "--tmpfs", "/var/lib/mysql:rw,size=512m",
               "-e", "MYSQL_ROOT_PASSWORD", "-e", "MYSQL_ROOT_HOST", IMAGE,
               f"--server-id={server_id}", "--default-storage-engine=InnoDB",
               "--sql-mode=STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION"]
    assert "127.0.0.1::3306" in command and "/var/lib/mysql:rw,size=512m" in command
    assert not any(arg in command for arg in ("--volume", "-v", "--mount", "--network=host"))
    findings = {"container": name, "platform": "linux/amd64", "image": IMAGE,
                "pre004_commit": PRE004, "schemas": [upgrade, fresh],
                "docker_engine": server["Version"], "docker_arch": server["Arch"]}
    context, container_id, result = None, None, 1
    try:
        print(f"Creating disposable container {name}; synthetic data only", flush=True)
        container_id = docker(*command, env=environment)
        details, = json.loads(docker("inspect", container_id))
        assert details["Name"] == "/" + name
        assert details["Config"]["Image"] == IMAGE
        assert details["Config"]["Labels"]["likehome.us72.run"] == run_id
        assert not details["HostConfig"].get("Binds")
        assert "/var/lib/mysql" in details["HostConfig"]["Tmpfs"]
        assert all(mount["Type"] == "tmpfs" for mount in details["Mounts"])
        ports = details["NetworkSettings"]["Ports"]
        assert set(ports) == {"3306/tcp", "33060/tcp"} or set(ports) == {"3306/tcp"}
        assert not ports.get("33060/tcp")
        published, = ports["3306/tcp"]
        assert published["HostIp"] == "127.0.0.1"
        port = int(published["HostPort"])
        assert port > 1024 and port != 3306
        allowed = ("127.0.0.1", port)

        def deny_other_network(event_name, event_args):
            if event_name == "socket.connect":
                assert event_args[1] == allowed, "Non-disposable network connection blocked"
            if event_name == "socket.getaddrinfo":
                assert event_args[:2] == allowed, "Non-disposable DNS lookup blocked"

        sys.addaudithook(deny_other_network)
        context = Context(dict(host=allowed[0], port=port, user="root", password=password,
                               connect_timeout=2, read_timeout=15, write_timeout=15,
                               charset="utf8mb4", autocommit=False), upgrade, fresh, server_id)
        findings["isolation"] = {"loopback_port": port, "tmpfs_only": True,
                                 "container_id": container_id, "server_id": server_id}
        deadline = time.monotonic() + 90
        while True:
            try:
                with context.connect() as connection:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT VERSION(), @@sql_mode, @@tx_isolation, @@default_storage_engine")
                        findings["server"] = cursor.fetchone()
                break
            except pymysql.OperationalError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Disposable MySQL did not become ready") from None
                time.sleep(0.5)
        assert "STRICT_TRANS_TABLES" in findings["server"][1]
        assert findings["server"][2:] == ("REPEATABLE-READ", "InnoDB")
        before_sql = subprocess.run(
            ["git", "show", f"{PRE004}:backend/database/like_home_database_init.sql"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        ).stdout
        assert "session_version" in before_sql and "guest_email" in before_sql
        assert "hotel_token" in before_sql and "reservation_change_events" not in before_sql
        with context.connect() as connection:
            execute_script(connection, rewrite_schema(before_sql, upgrade))
            seed_sql = """
                INSERT INTO users (user_id,email,password_hash,full_name) VALUES
                (7001,'pending@example.test','synthetic-only','Pending Owner'),
                (7002,'paid@example.test','synthetic-only','Paid Owner');
                INSERT INTO hotels (hotel_id,hotel_token,name) VALUES
                (7101,'synthetic-us72-property','Disposable Hotel');
                INSERT INTO room_types (room_type_id,hotel_id,type_name,price_per_night) VALUES
                (7201,7101,'Synthetic Rate',100.01),(7202,7101,'Synthetic Revised Rate',120.03);
                INSERT INTO reservations (reservation_id,user_id,room_type_id,guest_full_name,guest_email,
                    check_in_date,check_out_date,status,total_price,created_at) VALUES
                (7301,7001,7201,NULL,NULL,'2030-11-01','2030-11-03','confirmed',210.02,'2030-01-01 12:00:00'),
                (7302,7002,7201,'Synthetic Guest','guest@example.test','2030-11-10','2030-11-12',
                    'confirmed',210.02,'2030-01-01 12:00:00');
                INSERT INTO payments (payment_id,reservation_id,amount,payment_type,payment_status,created_at) VALUES
                (7401,7301,226.82,'booking','pending','2030-01-01 12:00:00'),
                (7402,7302,226.82,'booking','paid','2030-01-01 12:00:00');
            """
            execute_script(connection, seed_sql)
            connection.commit()
            previous = snapshot(connection)
            findings["before"] = previous
            execute_script(connection, rewrite_schema(
                (BACKEND / "database/migrations/004_add_reservation_change_persistence.sql").read_text(), upgrade))
            assert snapshot(connection) == previous, "Historical data changed"
            findings["after"] = snapshot(connection)
            findings["migration_004_applications"] = 1
            with connection.cursor() as cursor:
                cursor.execute("SELECT revision FROM reservations")
                assert cursor.fetchall() == ((0,), (0,))
                for table in ("reservation_change_events", "reservation_change_adjustments"):
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    assert cursor.fetchone() == (0,)
            execute_script(connection, rewrite_schema(
                (BACKEND / "database/like_home_database_init.sql").read_text(), fresh))
            execute_script(connection, seed_sql)
            connection.commit()
        context.evidence = findings
        print("MySQL 5.7.44 ready; migration applied once, historical data preserved, fresh schema installed", flush=True)
        result = pytest.main([str(Path(__file__).with_name("test_mysql57_contract.py")),
                              "-q", "-p", "no:cacheprovider"], plugins=[Plugin(context)])
        findings["pytest_exit_code"] = int(result)
    finally:
        if context:
            for engine in context.engines:
                engine.dispose()
        # docker run can create a container and then fail to start it. In that
        # case recover only our unique, labeled resource instead of leaking it.
        if not container_id:
            candidate = subprocess.run(
                ["docker", "--context", "desktop-linux", "inspect", name],
                capture_output=True, text=True,
            )
            if candidate.returncode == 0:
                details, = json.loads(candidate.stdout)
                assert details["Config"]["Labels"]["likehome.us72.run"] == run_id
                container_id = details["Id"]
        if container_id:
            details, = json.loads(docker("inspect", container_id))
            assert details["Config"]["Labels"]["likehome.us72.run"] == run_id
            docker("rm", "-f", container_id)
            findings["cleanup"] = "container removed; tmpfs discarded"
        assert set(docker("ps", "-aq").split()) == before_containers
        assert set(docker("volume", "ls", "-q").split()) == before_volumes
        findings["existing_container_and_volume_ids_preserved"] = True
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(findings, default=str, indent=2) + "\n")
        print(f"Disposable cleanup complete; findings: {args.evidence}", flush=True)
    return int(result)


if __name__ == "__main__":
    raise SystemExit(main())
