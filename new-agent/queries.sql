-- Azure SQL Database: casestudydb
-- Server: spend-agent-sql-treya.database.windows.net
-- Table: case_study_extractions

-- List all clients
SELECT 
    client_name,
    extraction_timestamp,
    updated_at
FROM case_study_extractions
ORDER BY extraction_timestamp DESC;

-- View full data for a specific client
SELECT *
FROM case_study_extractions
WHERE client_name = 'Advantia Health';

-- Count total extractions
SELECT COUNT(*) AS total_clients
FROM case_study_extractions;

-- View categories JSON for a client (parsed)
SELECT 
    client_name,
    JSON_VALUE(categories, '$.categories_summary.total_count') AS category_count,
    JSON_VALUE(categories, '$.categories_summary.total_savings') AS total_savings,
    JSON_VALUE(impact, '$.impact.financials.annual_savings.amount') AS annual_savings
FROM case_study_extractions;
