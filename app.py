from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import requests
from flask import (
    Flask,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


PROJECT_NAME = "Nimbus Nexus: EC2 Onboarding Portal"
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = Path(os.environ.get("DATABASE_PATH", BASE_DIR / "database.db"))
DEFAULT_LIMERICK_PATH = Path(os.environ.get("LIMERICK_PATH", BASE_DIR / "Limerick.txt"))
METADATA_BASE_URL = "http://169.254.169.254/latest/meta-data"
METADATA_FIELDS = {
    "Instance ID": "instance-id",
    "Instance Type": "instance-type",
    "Availability Zone": "placement/availability-zone",
    "Public IPv4": "public-ipv4",
}


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.update(
        DATABASE=str(DEFAULT_DB_PATH),
        SECRET_KEY=os.environ.get("FLASK_SECRET_KEY", "change-me-for-production"),
        PROJECT_NAME=PROJECT_NAME,
        AWS_METADATA_ENABLED=os.environ.get("AWS_METADATA_ENABLED", "1") != "0",
    )

    DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    @app.before_request
    def inject_project_name() -> None:
        g.project_name = app.config["PROJECT_NAME"]

    @app.teardown_appcontext
    def close_connection(_: Optional[BaseException]) -> None:
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.context_processor
    def add_project_context() -> Dict[str, str]:
        return {"project_name": app.config["PROJECT_NAME"]}

    @app.cli.command("init-db")
    def init_db_command() -> None:
        """Initialize the SQLite database schema."""
        init_db()
        print("Database initialised.")

    register_routes(app)

    with app.app_context():
        init_db()

    return app


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


def init_db() -> None:
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            first_name TEXT,
            last_name TEXT,
            email TEXT,
            job_title TEXT,
            favorite_service TEXT,
            region TEXT,
            bio TEXT,
            last_login TEXT
        )
        """
    )
    ensure_columns(db)
    db.commit()


def ensure_columns(db: sqlite3.Connection) -> None:
    """Add new profile columns if an older database is reused."""
    cursor = db.execute("PRAGMA table_info(users)")
    existing = {row[1] for row in cursor.fetchall()}
    alterations = {
        "job_title": "ALTER TABLE users ADD COLUMN job_title TEXT",
        "favorite_service": "ALTER TABLE users ADD COLUMN favorite_service TEXT",
        "region": "ALTER TABLE users ADD COLUMN region TEXT",
        "bio": "ALTER TABLE users ADD COLUMN bio TEXT",
        "last_login": "ALTER TABLE users ADD COLUMN last_login TEXT",
    }
    for column, statement in alterations.items():
        if column not in existing:
            db.execute(statement)


def fetch_instance_metadata() -> Dict[str, str]:
    """Best-effort retrieval of EC2 instance metadata."""
    if not current_app.config["AWS_METADATA_ENABLED"]:
        return {}

    metadata: Dict[str, str] = {}
    session = requests.Session()
    for label, path in METADATA_FIELDS.items():
        if metadata.get("error"):
            break
        try:
            response = session.get(f"{METADATA_BASE_URL}/{path}", timeout=0.2)
            response.raise_for_status()
            metadata[label] = response.text.strip()
        except requests.RequestException:
            metadata["error"] = (
                "Instance metadata is unavailable. If you are running locally, this is expected."
            )
    return metadata


def get_limerick_stats() -> Dict[str, Optional[str]]:
    if not DEFAULT_LIMERICK_PATH.exists():
        return {"error": "Limerick.txt not found."}

    content = DEFAULT_LIMERICK_PATH.read_text(encoding="utf-8")
    word_count = len(content.split())
    return {
        "word_count": word_count,
        "path": str(DEFAULT_LIMERICK_PATH.resolve()),
    }


def load_user(username: str) -> Optional[sqlite3.Row]:
    db = get_db()
    return db.execute(
        "SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (username,)
    ).fetchone()


def register_routes(app: Flask) -> None:
    @app.route("/", methods=["GET", "POST"])
    def login() -> str:
        if request.method == "POST":
            username = request.form["username"].strip()
            password = request.form["password"]
            db = get_db()
            user = load_user(username)

            if user is None:
                hashed_password = generate_password_hash(password)
                db.execute(
                    """
                    INSERT INTO users (username, password, last_login)
                    VALUES (?, ?, ?)
                    """,
                    (username, hashed_password, datetime.utcnow().isoformat()),
                )
                db.commit()
                flash("Welcome aboard! Let's tailor your cloud profile.", "info")
                return redirect(url_for("complete_profile", username=username))

            if check_password_hash(user["password"], password):
                db.execute(
                    "UPDATE users SET last_login = ? WHERE id = ?",
                    (datetime.utcnow().isoformat(), user["id"]),
                )
                db.commit()
                flash("Logged in successfully.", "success")
                return redirect(url_for("dashboard", username=user["username"]))

            flash("Incorrect password. Try again.", "error")

        return render_template("login.html")

    @app.route("/profile/<username>/complete", methods=["GET", "POST"])
    def complete_profile(username: str) -> str:
        user = load_user(username)
        if user is None:
            abort(404)

        if request.method == "POST":
            updates = (
                request.form.get("first_name", "").strip(),
                request.form.get("last_name", "").strip(),
                request.form.get("email", "").strip(),
                request.form.get("job_title", "").strip(),
                request.form.get("favorite_service", "").strip(),
                request.form.get("region", "").strip(),
                request.form.get("bio", "").strip(),
                user["username"],
            )
            db = get_db()
            db.execute(
                """
                UPDATE users
                   SET first_name = ?,
                       last_name = ?,
                       email = ?,
                       job_title = ?,
                       favorite_service = ?,
                       region = ?,
                       bio = ?
                 WHERE username = ?
                """,
                updates,
            )
            db.commit()
            flash("Profile saved. Time to explore your cloud footprint!", "success")
            return redirect(url_for("dashboard", username=user["username"]))

        return render_template("complete_profile.html", user=user)

    @app.route("/dashboard/<username>")
    def dashboard(username: str) -> str:
        user = load_user(username)
        if user is None:
            abort(404)

        limerick_stats = get_limerick_stats()
        metadata = fetch_instance_metadata()
        return render_template(
            "dashboard.html",
            user=user,
            limerick=limerick_stats,
            metadata=metadata,
        )

    @app.route("/about")
    def about():
        highlights = [
            {
                "title": "AWS Practitioner",
                "description": (
                    "Hands-on experience launching resilient stacks on EC2, "
                    "automating bootstrap scripts, and baking AMIs with repeatable tooling."
                ),
            },
            {
                "title": "Observability advocate",
                "description": (
                    "Builds health checks, layered logging, and metadata probes so cloud resources stay transparent."
                ),
            },
            {
                "title": "Security minded",
                "description": (
                    "Applies IAM least privilege, secrets management, and audited change pipelines to every deployment."
                ),
            },
        ]
        timeline = [
            ("2020", "Started the cloud journey focusing on EC2 and automation fundamentals."),
            ("2021", "Hardened multi-tier workloads with load balancers, ASGs, and blue/green rolls."),
            ("2022", "Expanded into container orchestration and hybrid networking."),
            ("2023", "Led cost-optimization and observability upgrades across production fleets."),
            ("2024", "Building portfolio-ready demos like Nimbus Nexus to showcase modern ops discipline."),
        ]
        return render_template("about.html", highlights=highlights, timeline=timeline)

    @app.route("/files/limerick")
    def download_limerick():
        if not DEFAULT_LIMERICK_PATH.exists():
            abort(404)
        return send_file(
            DEFAULT_LIMERICK_PATH,
            as_attachment=True,
            download_name="Limerick.txt",
        )

    @app.route("/health")
    def health():
        db_status = "ok"
        try:
            db = get_db()
            db.execute("SELECT 1")
        except sqlite3.Error:
            db_status = "error"

        return jsonify(
            {
                "status": "ok" if db_status == "ok" else "degraded",
                "database": db_status,
                "project": PROJECT_NAME,
            }
        )


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
