-- SPDX-FileCopyrightText: 2026 Malte Dreyer
-- SPDX-License-Identifier: MIT
-- Fix translatable-Werte für alle Prompts
-- Ausführen nach Deploy wenn translatable-Werte falsch sind

-- Diese Felder SOLLEN übersetzt werden (Text/Beschreibungen)
UPDATE prompts SET translatable = true WHERE internal_name IN (
    'short_description', 
    'public_description', 
    'disciplines', 
    'research_fields', 
    'specializations', 
    'keywords',
    'project_lead',      -- Titel können übersetzt werden
    'team_members',      -- Titel können übersetzt werden
    'goals', 
    'work_packages', 
    'methods', 
    'expected_results'
);

-- Diese Felder NICHT übersetzen (Namen, IDs, URLs, Institutionen)
UPDATE prompts SET translatable = false WHERE internal_name IN (
    'project_name',       -- Projektnamen bleiben
    'institution',        -- Institutionsnamen bleiben
    'funding_body',       -- DFG, BMBF etc. bleiben
    'funding_program',    -- Programmnamen bleiben
    'funding_id',         -- Kennzeichen bleiben
    'funding_period',     -- Datum bleibt
    'funding_volume',     -- Betrag bleibt
    'participating_institutions',  -- Namen bleiben
    'external_partners',  -- Namen bleiben
    'contact_person',     -- Namen bleiben
    'contact_email',      -- Email bleibt
    'project_website'     -- URL bleibt
);

-- Verifizierung
SELECT internal_name, display_name, translatable 
FROM prompts 
WHERE field_group IN ('basis', 'themen', 'foerderung', 'team', 'inhalte', 'kontakt')
ORDER BY translatable DESC, internal_name;
