#!/usr/bin/env bash
set -Eeuo pipefail

runtime_user="${RECPRO_MYSQL_RUNTIME_USER:?runtime user is required}"
runtime_password="${RECPRO_MYSQL_RUNTIME_PASSWORD:?runtime password is required}"
database_name="${MYSQL_DATABASE:?database name is required}"
root_password="${MYSQL_ROOT_PASSWORD:?root password is required}"
probe_id="${RECPRO_PERSISTENCE_PROBE_ID:?persistence probe id is required}"

if [[ ! "$runtime_user" =~ ^[a-z][a-z0-9_]{2,31}$ ]]; then
  echo "runtime user must match the approved identifier format" >&2
  exit 64
fi
if [[ ! "$database_name" =~ ^[a-z][a-z0-9_]{2,63}$ ]]; then
  echo "database name must match the approved identifier format" >&2
  exit 64
fi
if [[ ! "$runtime_password" =~ ^[A-Za-z0-9._~-]{16,128}$ ]]; then
  echo "runtime password must be 16-128 characters from the approved local set" >&2
  exit 64
fi
if [[ ! "$probe_id" =~ ^[a-z0-9][a-z0-9_-]{2,47}$ ]]; then
  echo "persistence probe id must match the isolated project identifier" >&2
  exit 64
fi

mysql_client=(
  mysql
  --protocol=socket
  --user=root
  "--password=${root_password}"
)

"${mysql_client[@]}" <<SQL
CREATE TABLE IF NOT EXISTS \`${database_name}\`.\`recpro_runtime_probe\` (
  \`probe_id\` VARCHAR(64) NOT NULL,
  \`created_at\` TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (\`probe_id\`)
) ENGINE=InnoDB;
INSERT IGNORE INTO \`${database_name}\`.\`recpro_runtime_probe\` (\`probe_id\`)
VALUES ('${probe_id}');
CREATE USER IF NOT EXISTS '${runtime_user}'@'%' IDENTIFIED BY '${runtime_password}';
GRANT SELECT, INSERT ON \`${database_name}\`.* TO '${runtime_user}'@'%';
SQL
