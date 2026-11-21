# EventCalendar — notes for the coding agent

* Spec: `docs/technical-spec.md` (Russian). Stages and acceptance criteria are in §9; work stage by stage.
* The owner wants features one at a time, each with manual testing and autotest coverage.
* The owner is not a server admin: deploy steps must be scripts (`deploy/*.sh`) with plain Russian messages.
* Harvey (`VETASKA/findclients-rte`) is the main event source and runs on the same server.
  The push contract is `docs/intake-api.md`; change both sides together and bump `schema` for breaking changes.
* Never overwrite moderator / organizer edits from an import (`Event.manual_fields`, `EventRevision`).
* Every first publication is moderated; bulk approval never grants organizer rights.
* Tests need PostgreSQL: `DATABASE_URL=… python -m pytest` (settings: `config/settings_test.py`).
* Interface languages: uk (default), en, pl. Store reference names as `{"uk": …, "en": …, "pl": …}`.
