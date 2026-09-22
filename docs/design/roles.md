# Role boundaries

FlexMapping distinguishes three roles: `viewer`, `editor` and `admin`. The
boundary that required a decision is the one between `editor` and `admin`.

An editor works on records. Registering a source, correcting a value in the
review queue, confirming an entity link and re-extracting a single source all
change one source and leave everything else as it was. If such a change is
wrong, the wrong value is visible in one profile and can be corrected there.

An administrator works on the configuration. Changing a prompt, adding a field,
adjusting a confidence threshold or editing the entity master data changes how
every subsequent extraction behaves, in every category that uses the affected
definition. A mistake there is not visible in one place. It appears gradually,
in results that look plausible, as sources are re-extracted over the following
days.

The two kinds of change therefore carry different roles, even though both are
write operations. The technical effort is identical; the recoverability is not.

Site generation, seeding and the factory reset are assigned to `admin` for a
different reason. They are not configuration changes but operations whose effect
extends beyond the database: generation empties a directory on the filesystem,
and the factory reset removes all records. Both are recoverable only from a
backup.

The `viewer` role exists because the most frequent request in practice is to
look at the current state without changing it. Without a read-only role, that
request can only be answered by granting write access.

Single sign-on is not implemented. The user table stores a password hash and a
role. When an external identity provider is added, the password hash becomes
optional and an external subject identifier is stored alongside it; the role
column and the dependency that enforces it remain unchanged.
