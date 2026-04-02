#!/bin/bash
set -e

echo "PORT=${PORT:-not set}"
echo "DATABASE_URL=${DATABASE_URL:+set (hidden)}"

# Generate secrets.toml from environment variables (for Railway deployment)
if [ -n "$AUTH_CLIENT_ID" ]; then
    mkdir -p .streamlit
    cat > .streamlit/secrets.toml <<EOF
[auth]
redirect_uri = "$AUTH_REDIRECT_URI"
cookie_secret = "$AUTH_COOKIE_SECRET"
client_id = "$AUTH_CLIENT_ID"
client_secret = "$AUTH_CLIENT_SECRET"
server_metadata_url = "$AUTH_SERVER_METADATA_URL"
EOF
    echo "Generated .streamlit/secrets.toml from env vars."
fi

# Database schema initialization
if [ -z "$DATABASE_URL" ]; then
    echo "ERROR: DATABASE_URL is not set. Add a Postgres plugin on Railway."
    exit 1
fi

python - <<'PYEOF'
import psycopg2, os, sys
try:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    with open("pipeline/schema.sql") as f:
        cur.execute(f.read())
    conn.commit()
    print("Schema initialized OK.")

    # Seed admin user from env vars (idempotent)
    admin_email = os.environ.get("ADMIN_EMAIL")
    admin_password = os.environ.get("ADMIN_PASSWORD")
    if admin_email and admin_password:
        import bcrypt
        pw_hash = bcrypt.hashpw(admin_password.encode("utf-8"),
                                bcrypt.gensalt()).decode("utf-8")
        cur.execute(
            """INSERT INTO app_users (email, name, password_hash, auth_provider)
               VALUES (%s, %s, %s, 'local')
               ON CONFLICT (email) DO NOTHING""",
            (admin_email, "Admin", pw_hash),
        )
        conn.commit()
        print(f"Admin user seeded: {admin_email}")

    cur.close()
    conn.close()
except Exception as e:
    print(f"Schema init failed: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF

exec streamlit run app.py \
    --server.port "${PORT:-8501}" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false
