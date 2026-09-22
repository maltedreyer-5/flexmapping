# Security policy

## Supported versions

Version 1.0.0 is the current release. Security fixes are applied to the latest
release.

## Reporting a vulnerability

Report privately through GitHub Security Advisories at
`https://github.com/maltedreyer-5/flexmapping/security/advisories/new`, or by email to
the address listed on the repository owner's GitHub profile. Do not open a
public issue for a security report.

Please include the affected version, the configuration relevant to the finding,
and the steps to reproduce it. An acknowledgement follows within five working
days.

## Deployment assumptions

The design assumes the following. Where an assumption does not hold, the
protections described below do not hold either.

1. **The instance runs inside an organisation's network**, not on the public
   internet.
2. **A reverse proxy terminates TLS.** The application serves HTTP only.
   `SESSION_COOKIE_SECURE=true` is set once TLS is in place.
3. **The LLM endpoint is trusted.** Its responses are stored and published
   after review, and they are not treated as hostile input.
4. **Operators are trusted within their role.** Access control separates roles;
   it does not defend against an operator misusing their own role.
5. **The database and Redis are reachable only from the application.** The
   supplied Compose file publishes neither.

## In scope

| Area | Protection |
|---|---|
| Authentication | Account required for the admin interface and the admin API. Argon2 password hashing, re-hashed on login when parameters change. Signed session cookies. HTTP Basic against the same account store. Fixed delay after a failed login. Constant-time comparison for unknown usernames. |
| Authorization | Three roles. `viewer` reads; `editor` curates records; `admin` changes configuration, entity master data and runs destructive operations. |
| Configuration | With `ENVIRONMENT=production`, startup aborts while a `CHANGE_ME` placeholder remains, or while `DEBUG` or `DOCS_ENABLED` is enabled. |
| Error output | Exception text is returned to HTTP clients only with `DEBUG` enabled. |
| API surface | `/docs`, `/redoc` and `/openapi.json` are disabled by default. |
| CORS | Restricted to the configured origins; the default is localhost. |
| Data loss | Site generation refuses to clear a non-empty output directory without its marker file. |
| Input handling | NULL bytes and control characters are removed from crawled content before storage. All database access goes through parameterised SQLAlchemy queries. |

## Not in scope

The following are deliberate limits of the current design. They are not
vulnerabilities, and reports about them will be closed with a reference to this
section.

**Operator error.** An account with the `admin` role can delete every record
through the factory reset endpoint, and can point `PUBLIC_SITE_DIR` at a
directory whose contents will then be deleted. Both are documented operations
of an authorised role.

**No account lockout.** A failed login incurs a fixed delay. There is no
lockout after repeated failures and no CAPTCHA. Rate limiting at the reverse
proxy is the intended mitigation.

**No single sign-on.** Accounts are local. Shibboleth, LDAP and OIDC are not
implemented.

**No second factor.** Password authentication only.

**No password reset.** Passwords are changed by an administrator against the
database.

**No audit trail.** The account that last edited an extraction is recorded, and
the factory reset is logged with the account that triggered it. There is no
general log of who changed what.

**No per-category permissions.** A role applies to the whole instance.

**Crawled content is not sanitised for the generated site beyond control
characters.** The site generator escapes values when rendering templates, but
the crawled Markdown originates from third-party pages. Crawl only sources you
are willing to republish.

**Prompt injection is not defended against.** A crawled page can contain text
addressing the model. The review queue and the confidence thresholds are the
means by which such results are caught; there is no filter that detects the
attempt.

**Dependency vulnerabilities.** Versions are pinned in `requirements.txt` and
are not updated automatically. Watch the pinned set.

## Hardening checklist

- Replace every `CHANGE_ME` value and set `ENVIRONMENT=production`.
- Change the bootstrap administrator password after the first login.
- Place a reverse proxy in front and set `SESSION_COOKIE_SECURE=true`.
- Restrict `/admin` and `/admin-ui` by network at the proxy.
- Give `PUBLIC_SITE_DIR` a directory used for nothing else.
- Set `REDIS_KEY_PREFIX` if Redis is shared.
- Create accounts with `viewer` or `editor` where `admin` is not required.
- Set up database backups; see [docs/operations.md](docs/operations.md).
