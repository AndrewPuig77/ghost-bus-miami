# Postgres + PostGIS for both x86 laptops and ARM servers (Oracle Ampere).
# The postgis/postgis image is published for amd64 only, so install PostGIS from the
# PostgreSQL apt repository, which the official postgres image already has configured.
FROM postgres:17-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-17-postgis-3 \
    && rm -rf /var/lib/apt/lists/*
