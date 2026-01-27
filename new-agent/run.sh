#!/bin/bash
# Run the Case Study Agent with Azure SQL support
# Usage: ./run.sh

# Change to script directory
cd "$(dirname "$0")"

# Load Azure SQL environment variables
source azure_setup.sh

# Run with ARM Python
/opt/homebrew/bin/python3.11 -m src "$@"
