#!/bin/bash
set -e

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
fi

exec streamlit run app.py \
    --server.port "${PORT:-8501}" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false
