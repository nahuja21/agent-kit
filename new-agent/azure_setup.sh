#!/bin/bash
# Azure SQL Database Configuration
# Run: source azure_setup.sh

# Enable Azure SQL integration
export AZURE_SQL_ENABLED=true

# Azure SQL Server details
export AZURE_SQL_SERVER=spend-agent-sql-treya.database.windows.net
export AZURE_SQL_DATABASE=casestudydb
export AZURE_SQL_USERNAME=spendadmin
export AZURE_SQL_PASSWORD="TreyaCaseStudy2026!"

# Table name (optional, defaults to case_study_extractions)
export AZURE_SQL_TABLE=case_study_extractions

echo "Azure SQL environment variables set:"
echo "  Server: $AZURE_SQL_SERVER"
echo "  Database: $AZURE_SQL_DATABASE"
echo "  User: $AZURE_SQL_USERNAME"
echo "  Table: $AZURE_SQL_TABLE"
echo "  Enabled: $AZURE_SQL_ENABLED"
