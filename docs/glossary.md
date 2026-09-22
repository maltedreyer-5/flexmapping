# Glossary

| Term | |
|---|---|
| **Category** | a content type. Defines which fields a record has, which prompt extracts each, and how the result is rendered. One YAML file per category. |
| **Field group** | a named set of fields within a category, used to structure the profile. `active_groups` decides which groups appear. |
| **Prompt** | the definition of one field: the instruction that extracts it, the optional instruction that validates it, its confidence threshold, and whether it is translated. |
| **Extract** | the first LLM call for a field. Produces the raw result. |
| **Validate** | the second LLM call for the same field. Evaluates the raw result against the source text and returns a quality class, a score, a justification, and the value to store. |
| **Quality class** | `HIGH`, `MEDIUM`, `LOW` or `INSUFFICIENT`. |
| **Confidence** | the numeric score from validation, between 0 and 1. Compared against the prompt's `required_confidence`. |
| **Raw result / validated result** | the output of the extract and validate calls respectively, stored in separate columns. They may differ. |
| **Manual edit** | a value corrected by an operator. Stored separately and not overwritten by machine output unless explicitly requested. |
| **Source** | one registered URL together with its crawled Markdown, its extractions and its profile. |
| **Steckbrief / profile** | the Markdown document rendered from a source's extractions using the category template. The database table and several identifiers use the German word; the interface says "profile". |
| **Entity** | a canonical name for an institution or a location, with its variants. "TUM" and "Technical University of Munich" are variants of one entity. |
| **Entity normalization** | matching an extracted name against the entity inventory. Above 0.9 confidence the link is created, between 0.6 and 0.9 a review item is produced, below that the suggestion is discarded. |
| **Review queue** | the view collecting fields below their threshold and pending entity normalizations. |
| **Job** | one unit of queued work: crawl, extract, validate, normalize, translate or generate. |
| **Wave** | a set of prompts whose dependencies are satisfied, run in parallel. |
| **Circuit breaker** | the component that stops calling the LLM after repeated failures and admits a single probe request after a pause. |
| **Publishing** | marking a profile for inclusion in the generated site. Generation and publishing are separate steps. |
