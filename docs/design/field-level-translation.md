# Translation at field level

Translation runs once per field, not once per profile. Each translatable field
becomes its own LLM call.

The alternative would be to translate the rendered Markdown of a profile in one
call. That document already exists at the time of translation, and one call is
cheaper than twenty. It was not chosen because the result has to be taken apart
again afterwards.

A profile is a Markdown document with headings. To store the translation, the
system has to know which passage belongs to which field, and the only available
key is the heading. A model translating the document also translates the
headings, and a translated heading no longer matches the mapping that assigns
headings to field names. The assignment then fails without any error: the
affected section is stored under a name that matches no prompt, and the field
appears untranslated while the job reports success.

Translating per field avoids the reconstruction entirely. The field name is
known before the call is made, because the call is issued for that field.

The second consequence concerns context. A per-field call can carry information
that a whole-document call cannot direct at any particular passage: the field's
label, its category, and the `translation_context` from the category
configuration, which states in one sentence what the field means. Short fields
benefit from this most, because a label alone is often ambiguous.

The cost is call volume. A profile with twenty translatable fields requires
twenty calls instead of one. For a self-hosted endpoint this is the dominant
factor in the translation stage, and it is the reason translation carries the
lowest job priority of all pipeline stages.
