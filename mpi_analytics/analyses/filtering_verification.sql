-- Filtering Verification Analysis
-- This analysis checks the filtering logic in the staging and integration models

-- Check 1: Source table distribution by status and validation_score
SELECT
    'source_table' as table_name,
    status,
    CASE
        WHEN validation_score IS NULL THEN 'NULL'
        WHEN validation_score <= {{ var('min_validation_score') }} THEN '≤' || {{ var('min_validation_score') }}
        ELSE '>' || {{ var('min_validation_score') }}
    END as validation_score_bucket,
    COUNT(*) as record_count
FROM {{ source('public', 'model_extracted_data') }}
WHERE model_name = 'gemini-2.0-flash'
GROUP BY status, validation_score_bucket
ORDER BY record_count DESC

UNION ALL

-- Check 2: Staging table distribution (after basic filtering)
SELECT
    'staging_table' as table_name,
    status,
    CASE
        WHEN validation_score IS NULL THEN 'NULL'
        WHEN validation_score <= {{ var('min_validation_score') }} THEN '≤' || {{ var('min_validation_score') }}
        ELSE '>' || {{ var('min_validation_score') }}
    END as validation_score_bucket,
    COUNT(*) as record_count
FROM {{ ref('stg__model_extracted_data') }}
GROUP BY status, validation_score_bucket
ORDER BY record_count DESC

UNION ALL

-- Check 3: Integration table distribution (after all filtering)
SELECT
    'integration_table' as table_name,
    status,
    CASE
        WHEN validation_score IS NULL THEN 'NULL'
        WHEN validation_score <= {{ var('min_validation_score') }} THEN '≤' || {{ var('min_validation_score') }}
        ELSE '>' || {{ var('min_validation_score') }}
    END as validation_score_bucket,
    COUNT(*) as record_count
FROM {{ ref('int__model_extracted_data') }}
GROUP BY status, validation_score_bucket
ORDER BY record_count DESC