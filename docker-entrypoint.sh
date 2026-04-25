#!/bin/sh
set -eu

if [ "${DJANGO_DB_ENGINE:-django.db.backends.postgresql}" = "django.db.backends.postgresql" ]; then
    db_host="${POSTGRES_HOST:-db}"
    db_port="${POSTGRES_PORT:-5432}"

    echo "Waiting for PostgreSQL at ${db_host}:${db_port}..."
    while ! nc -z "${db_host}" "${db_port}"; do
        sleep 1
    done
fi

python manage.py migrate --noinput

if [ "${SEED_MOCK_DATA:-false}" = "true" ]; then
    python manage.py seed_mock_data || true
fi

exec "$@"
