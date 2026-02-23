#!/usr/bin/env python3
"""
Quick script to check Azure SQL database contents.

Usage:
    source azure_setup.sh
    python check_database.py
"""

import pyodbc
import json
import sys

# Import config
sys.path.insert(0, '.')
from src.config import get_azure_connection_string, AZURE_SQL_TABLE, AZURE_SQL_ENABLED

def main():
    print("\n" + "="*60)
    print("AZURE SQL DATABASE CHECK")
    print("="*60)
    
    print(f"\nAZURE_SQL_ENABLED: {AZURE_SQL_ENABLED}")
    
    if not AZURE_SQL_ENABLED:
        print("\n❌ Azure SQL is DISABLED!")
        print("Run: source azure_setup.sh")
        return
    
    print(f"Table: {AZURE_SQL_TABLE}")
    
    try:
        conn_str = get_azure_connection_string()
        print("\nConnecting to Azure SQL...")
        
        conn = pyodbc.connect(conn_str, timeout=30)
        cursor = conn.cursor()
        
        # Get all clients
        cursor.execute(f"""
            SELECT id, client_name, extraction_timestamp, updated_at
            FROM {AZURE_SQL_TABLE}
            ORDER BY updated_at DESC
        """)
        
        rows = cursor.fetchall()
        
        print(f"\n✓ Connected! Found {len(rows)} client(s):\n")
        
        if not rows:
            print("  (No clients in database yet)")
            print("  Run /agent to extract and save a client.")
        else:
            print(f"{'ID':<5} {'Client Name':<30} {'Extracted':<20} {'Updated':<20}")
            print("-" * 75)
            for row in rows:
                extracted = str(row[2])[:19] if row[2] else "N/A"
                updated = str(row[3])[:19] if row[3] else "N/A"
                print(f"{row[0]:<5} {row[1]:<30} {extracted:<20} {updated:<20}")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    main()
