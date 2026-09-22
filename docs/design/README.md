# Design notes

These notes explain decisions in the current code whose reasoning is not
evident from reading it. They describe why the code is as it is, not how it
came to be.

| Note | Subject |
|---|---|
| [roles.md](roles.md) | Why `editor` and `admin` are separated where they are |
| [field-level-translation.md](field-level-translation.md) | Why translation runs per field rather than per document |
| [output-directory-guard.md](output-directory-guard.md) | Why the site generator requires a marker file before deleting |
