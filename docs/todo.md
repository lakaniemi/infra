# To do

- **Backups:** a nightly `pg_dump` of each database, copied off the server, and a test restore. Hetzner's server backups don't do this: they copy the disk while Postgres runs, so the database copy isn't guaranteed to be consistent. Not decided yet: where to store them (Hetzner Storage Box, Object Storage or another provider); check current prices first.
- **Monitoring:** an external uptime check, and alerts when a deploy or backup fails.
