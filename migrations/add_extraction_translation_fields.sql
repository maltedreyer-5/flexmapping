-- SPDX-FileCopyrightText: 2026 Malte Dreyer
-- SPDX-License-Identifier: MIT
-- Migration: Add translation fields to extractions table
-- Run this BEFORE deploying the new code

-- Add translation columns to extractions
ALTER TABLE extractions 
ADD COLUMN IF NOT EXISTS validated_result_en TEXT;

ALTER TABLE extractions 
ADD COLUMN IF NOT EXISTS translation_status VARCHAR(20) DEFAULT 'pending';

ALTER TABLE extractions 
ADD COLUMN IF NOT EXISTS translated_at TIMESTAMP WITH TIME ZONE;

-- Add check constraint for translation_status
ALTER TABLE extractions 
DROP CONSTRAINT IF EXISTS extractions_translation_status_check;

ALTER TABLE extractions 
ADD CONSTRAINT extractions_translation_status_check 
CHECK (translation_status IN ('pending', 'translated', 'skipped', 'failed'));

-- Create index for faster translation queries
CREATE INDEX IF NOT EXISTS idx_extractions_translation_status 
ON extractions(translation_status);

-- Optional: Drop old SteckbriefTranslation table (not needed anymore)
-- DROP TABLE IF EXISTS steckbrief_translations;

-- Verify
SELECT column_name, data_type, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'extractions' 
AND column_name IN ('validated_result_en', 'translation_status', 'translated_at');
