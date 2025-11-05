# Nimbus Nexus: EC2 Onboarding Portal

Nimbus Nexus is a Flask application that I use to demonstrate how I approach building and operating workloads on Amazon EC2. It highlights secure authentication, schema evolution, observability endpoints, and live instance metadata discovery - the same guardrails I rely on in production.

Deploy it to an EC2 instance (or run locally) to experience the full onboarding flow, including cloud-aware dashboards and health checks that plug neatly into monitoring pipelines.

---

## Features

- **Modernized authentication:** Passwords are hashed with Werkzeug utilities, users onboard themselves, and profile data is captured in an auditable SQLite schema.
- **AWS-aware dashboard:** Surfaces EC2 instance metadata, application health, and file-based artifacts so operators instantly understand environment state.
- **Schema resilience:** Automatic migrations extend legacy databases with new columns, keeping deployments backward compatible.
- **Operational tooling:** `/health` endpoint for uptime probes, `/files/limerick` for asset delivery, and `flask --app app init-db` to bootstrap infrastructure.
- **Premium UI:** Responsive design, reusable templates, and portfolio-friendly copy tailored to my experience.

---

## Quickstart (local development)

```bash
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
flask --app app run --debug
```

Visit `http://127.0.0.1:5000` and log in with any username/password combination. New users will be prompted to complete a cloud-focused profile that drives the dashboard experience.

---

## Deploying on Amazon EC2

1. **Provision the instance**
   - Launch an Ubuntu 22.04 t3.micro (or larger) in your desired region.
   - Open inbound security group rules for HTTP/HTTPS (80/443) and optionally port 5000 during testing.

2. **Bootstrap with user data (optional but recommended)**
   ```bash
   #!/bin/bash
   apt-get update && apt-get install -y python3-pip python3-venv nginx
   useradd -m flasksvc || true
   su - flasksvc <<'EOF'
   git clone https://github.com/<your-username>/<your-repo>.git app
   cd app
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   flask --app app init-db
   EOF
   ```

3. **Run behind Gunicorn + Nginx**
   ```bash
   sudo tee /etc/systemd/system/nimbus.service <<'UNIT'
   [Unit]
   Description=Gunicorn instance to serve Nimbus Nexus
   After=network.target

   [Service]
   User=flasksvc
   Group=www-data
   WorkingDirectory=/home/flasksvc/app
   Environment="FLASK_SECRET_KEY=<replace-me>"
   ExecStart=/home/flasksvc/app/.venv/bin/gunicorn --bind 0.0.0.0:8000 app:app

   [Install]
   WantedBy=multi-user.target
   UNIT

   sudo systemctl enable --now nimbus

   sudo tee /etc/nginx/sites-available/nimbus <<'NGINX'
   server {
       listen 80;
       server_name _;

       location / {
           proxy_pass http://127.0.0.1:8000;
           include proxy_params;
       }
   }
   NGINX

   sudo ln -s /etc/nginx/sites-available/nimbus /etc/nginx/sites-enabled/
   sudo systemctl restart nginx
   ```

4. **Validate the deployment**
   - Check `curl http://<instance-ip>/health` for a fast health response.
   - Log in via the root path to confirm metadata cards populate (only on EC2 with metadata service access).

---

## Configuration

Environment variables make the application flexible:

| Variable | Purpose | Default |
| --- | --- | --- |
| `DATABASE_PATH` | Absolute/relative path to the SQLite database | `database.db` in the project folder |
| `LIMERICK_PATH` | Location of the downloadable `Limerick.txt` asset | `Limerick.txt` in the project folder |
| `FLASK_SECRET_KEY` | Secret for cookie signing and flash messaging | `change-me-for-production` |
| `AWS_METADATA_ENABLED` | Set to `0` to skip metadata lookups (useful locally) | `1` |

Running `flask --app app init-db` ensures schema migrations apply before traffic arrives.

---

## Testing the health contract

The `/health` endpoint performs a lightweight database check and returns JSON:

```bash
curl http://127.0.0.1:5000/health
# {"status":"ok","database":"ok","project":"Nimbus Nexus: EC2 Onboarding Portal"}
```

Use this in Route 53 health checks, ALB target groups, or third-party monitoring to maintain confidence in the deployment.

---

## Portfolio talking points

- Demonstrates infrastructure-as-code mindset with user data and systemd templates.
- Highlights security practices via hashed credentials and secret management options.
- Provides observability hooks (health check, metadata inspection) to keep operators informed.
- Wrapped in a polished UI that tells the story of how I deliver on AWS.

Looking to collaborate or hire? Reach out - I'd love to bring the same rigor to your EC2 workloads.
