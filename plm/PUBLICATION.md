# DeepLinkPLM source snapshot

2026-10-12 latest local code, published with user approval in `plm/`. ERP files and the default branch are unchanged.

Includes frontend, backend, migrations, tests and integration components. Excludes live environment files, initial account credentials, database backups, business uploads and runtime output. The local initialized 41 archives / 42 physical mold sets are database records, not part of this source upload.

Latest scoped verification: 34 backend tests passed; backend package succeeded. Previous full baseline: 422 backend / 240 frontend tests, type check and builds passed; not rerun for publication. Production deployment, external synchronization and trial start remain disabled and require separate authorization.

Configure credentials through private environment variables; never use local development sample accounts in production. Phone-watch database backups and PLM uploads must be provisioned separately.
