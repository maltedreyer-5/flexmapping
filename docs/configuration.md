# Configuration

Two things are configured separately: **what is captured**, in YAML category
files, and **how the system runs**, in environment variables.

## Category definitions

A category is one YAML file in `app/config/categories/`. The file name is free;
the `internal_name` inside identifies the category.

```yaml
category:
  internal_name: ai_service          # identifier, lower case and underscores
  display_name: KI-Service           # shown in the interface
  display_name_en: AI Service        # shown on the English site
  field_groups:                      # which fields belong to which section
    base: [service_name, institution, description]
    contact: [contact_person, contact_email]
  active_groups: [base, contact]     # which sections appear in a profile
  steckbrief_template: |             # Markdown with $variable placeholders
    # $service_name
    **Institution:** $institution

    ## Beschreibung
    $description

prompts:
  - internal_name: description       # must match the template variable
    display_name: Beschreibung
    display_name_en: Description
    field_group: base
    translatable: true
    translation_context: >
      What the service offers and to whom.
    prompt_template: |
      Extract a description of the service from the text.
      Format: two to four sentences.
      If not stated: "Nicht angegeben"
```

### Required fields

`validate_config()` in `app/seed.py` enforces these, and
`tests/test_category_configs.py` checks every shipped file against it:

| Section | Required |
|---|---|
| `category` | `internal_name`, `display_name`, `steckbrief_template`, `field_groups`, `active_groups` |
| each prompt | `internal_name`, `display_name`, `field_group`, and `prompt_template` or `extract_prompt` |

Additionally: prompt `internal_name` values must be unique within the file, and
every field named in `field_groups` must have a prompt.

### Optional prompt fields

| Field | Effect |
|---|---|
| `display_name_en` | label on the English site |
| `output_format` | format instruction appended to the prompt |
| `translatable` | whether the field is translated; default false |
| `translation_context` | a sentence telling the translator what the field means |
| `entity_type` | `university` or `location`; sends the value through entity normalization |
| `validate_template` | custom validation prompt; a generic one is used otherwise |
| `required_confidence` | minimum score; below it the field goes to the review queue |
| `depends_on` | internal names whose values are passed in as context |

### Template variables

`steckbrief_template` uses `$variable` or `${variable}`, where the name is a
prompt `internal_name`. A variable with no value is replaced with `-`, so an
unfilled placeholder never reaches a published page. A variable naming no
prompt stays empty and is reported in the interface.

### Loading a category

New and changed files are read on application start, and on demand from
**Configuration → Reload categories**. Two modes: load new categories only, or
overwrite every category from the files. The second discards changes made in the
interface.

The YAML files are the single source of truth. The database rows are a copy the
admin interface may edit; **Configuration → Category export** writes the current
database state back out as YAML, individually or as a ZIP.

### Language of the shipped prompts

The four shipped category definitions are written in German and instruct the
model to answer in German. The prompt text is what determines the output
language; there is no separate language setting. Capturing sources in another
language means writing category files in that language.

## Environment variables

Every setting is listed in `.env.example` with its default. The ones that
change behaviour most:

| Variable | Default | |
|---|---|---|
| `LLM_BASE_URL` | `http://localhost:8001/v1` | OpenAI-compatible endpoint |
| `LLM_MODEL` | `current-best` | model name passed through |
| `LLM_REQUESTS_PER_MINUTE` | `30` | pool-wide token bucket |
| `LLM_REQUEST_DELAY` | `2.0` | minimum seconds between calls, per worker |
| `NUM_WORKERS` | `3` | parallel job processors |
| `MAX_CONCURRENT_LLM` | `5` | semaphore across the pool |
| `CRAWLER_MAX_PAGES` | `5` | subpages per source in multi-page mode |
| `CRAWLER_DEFAULT_RATE_LIMIT` | `1.0` | requests per second, per domain |
| `CRAWLER_RESPECT_ROBOTS` | `true` | |
| `CRAWLER_VERIFY_SSL` | `true` | |
| `CIRCUIT_BREAKER_FAILURE_THRESHOLD` | `10` | consecutive failures before pausing |
| `PUBLIC_SITE_DIR` | `./public` | **emptied on every generation run** |
| `DOCS_ENABLED` | `false` | exposes `/docs` and `/redoc` |
| `DEBUG` | `false` | returns exception text to HTTP clients |

`FLEXMAP_CONFIG_DIR` overrides the location of the category files. The older
name `PROMPTKI_CONFIG_DIR` is still honoured if the new one is unset.

## Scope

Changing a prompt does not re-extract anything; existing values stay until a
re-extraction is triggered. A prompt `internal_name` is referenced by the
template variable of the same name and by existing extractions, so renaming one
means updating both. Field group keys and category internal names are stored in
the database; renaming them in YAML does not migrate existing rows.
