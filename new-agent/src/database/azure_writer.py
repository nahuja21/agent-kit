"""
Azure SQL Database Writer.

Handles saving case study extraction results to Azure SQL Database.
Each client gets one row with 8 columns:
- client_name (VARCHAR)
- extraction_timestamp (DATETIME)
- project_scope (NVARCHAR(MAX) - JSON)
- client_context (NVARCHAR(MAX) - JSON)
- engagement_background (NVARCHAR(MAX) - JSON)
- impact (NVARCHAR(MAX) - JSON)
- categories (NVARCHAR(MAX) - JSON)
- case_study (NVARCHAR(MAX) - JSON)
- battlecards (NVARCHAR(MAX) - JSON)
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

try:
    import pyodbc
    PYODBC_AVAILABLE = True
except ImportError:
    PYODBC_AVAILABLE = False


class AzureSQLWriter:
    """
    Writer for saving extraction results to Azure SQL Database.
    
    Usage:
        writer = AzureSQLWriter(connection_string)
        writer.save_extraction(
            client_name="Advantia Health",
            project_scope={...},
            client_context={...},
            ...
        )
    """
    
    # SQL to create the table if it doesn't exist
    CREATE_TABLE_SQL = """
    IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = '{table_name}')
    BEGIN
        CREATE TABLE {table_name} (
            id INT IDENTITY(1,1) PRIMARY KEY,
            client_name NVARCHAR(255) NOT NULL,
            extraction_timestamp DATETIME2 NOT NULL,
            project_scope NVARCHAR(MAX),
            client_context NVARCHAR(MAX),
            engagement_background NVARCHAR(MAX),
            impact NVARCHAR(MAX),
            categories NVARCHAR(MAX),
            case_study NVARCHAR(MAX),
            battlecards NVARCHAR(MAX),
            created_at DATETIME2 DEFAULT GETUTCDATE(),
            updated_at DATETIME2 DEFAULT GETUTCDATE()
        );
        
        CREATE INDEX idx_client_name ON {table_name} (client_name);
        CREATE INDEX idx_extraction_timestamp ON {table_name} (extraction_timestamp);
    END
    """
    
    # SQL to insert a new extraction
    INSERT_SQL = """
    INSERT INTO {table_name} (
        client_name,
        extraction_timestamp,
        project_scope,
        client_context,
        engagement_background,
        impact,
        categories,
        case_study,
        battlecards
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    
    # SQL to update existing extraction (upsert by client_name)
    UPSERT_SQL = """
    MERGE {table_name} AS target
    USING (SELECT ? AS client_name) AS source
    ON target.client_name = source.client_name
    WHEN MATCHED THEN
        UPDATE SET
            extraction_timestamp = ?,
            project_scope = ?,
            client_context = ?,
            engagement_background = ?,
            impact = ?,
            categories = ?,
            case_study = ?,
            battlecards = ?,
            updated_at = GETUTCDATE()
    WHEN NOT MATCHED THEN
        INSERT (
            client_name,
            extraction_timestamp,
            project_scope,
            client_context,
            engagement_background,
            impact,
            categories,
            case_study,
            battlecards
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
    """
    
    def __init__(self, connection_string: str, table_name: str = "case_study_extractions"):
        """
        Initialize the Azure SQL writer.
        
        Args:
            connection_string: ODBC connection string for Azure SQL
            table_name: Name of the table to store extractions
        """
        if not PYODBC_AVAILABLE:
            raise ImportError(
                "pyodbc is not installed. Install it with: pip install pyodbc\n"
                "You also need the ODBC Driver 18 for SQL Server installed on your system."
            )
        
        self.connection_string = connection_string
        self.table_name = table_name
        self._connection: Optional[pyodbc.Connection] = None
    
    def connect(self, retries: int = 3, debug_callback=None) -> pyodbc.Connection:
        """Establish connection to Azure SQL with retry logic."""
        import time
        
        def log(msg):
            if debug_callback:
                debug_callback(msg)
            else:
                print(msg)
        
        if self._connection is not None:
            log("[DEBUG] Testing existing connection...")
            try:
                cursor = self._connection.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
                log("[DEBUG] Existing connection is valid")
                return self._connection
            except Exception as e:
                log(f"[DEBUG] Existing connection dead: {e}")
                self._connection = None
        
        last_error = None
        for attempt in range(retries):
            log(f"[DEBUG] Connection attempt {attempt + 1}/{retries}")
            log(f"[DEBUG] Connection string: {self.connection_string[:50]}...")
            
            try:
                log("[DEBUG] Calling pyodbc.connect()...")
                start_time = time.time()
                
                # Use a shorter timeout and no attrs_before (simpler)
                self._connection = pyodbc.connect(
                    self.connection_string,
                    timeout=30  # 30 second timeout
                )
                
                elapsed = time.time() - start_time
                log(f"[DEBUG] pyodbc.connect() returned in {elapsed:.1f}s")
                
                # Verify connection works
                log("[DEBUG] Verifying with SELECT 1...")
                cursor = self._connection.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
                log("[DEBUG] Connection verified!")
                return self._connection
                
            except Exception as e:
                elapsed = time.time() - start_time
                log(f"[DEBUG] Attempt {attempt + 1} failed after {elapsed:.1f}s: {e}")
                last_error = e
                self._connection = None
                if attempt < retries - 1:
                    wait_time = (attempt + 1) * 3
                    log(f"[DEBUG] Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                continue
        
        if last_error:
            raise last_error
        return self._connection
    
    def close(self) -> None:
        """Close the database connection."""
        if self._connection:
            self._connection.close()
            self._connection = None
    
    def ensure_table_exists(self) -> None:
        """Create the table if it doesn't exist."""
        conn = self.connect()
        cursor = conn.cursor()
        
        sql = self.CREATE_TABLE_SQL.format(table_name=self.table_name)
        cursor.execute(sql)
        conn.commit()
        cursor.close()
    
    def save_extraction(
        self,
        client_name: str,
        project_scope: dict,
        client_context: dict,
        engagement_background: dict,
        impact: dict,
        categories: dict,
        case_study: dict,
        battlecards: dict,
        extraction_timestamp: Optional[datetime] = None,
        upsert: bool = True,
    ) -> int:
        """
        Save extraction results to Azure SQL.
        
        Args:
            client_name: Name of the client
            project_scope: Project scope data (will be JSON serialized)
            client_context: Client context data
            engagement_background: Engagement background data
            impact: Impact data
            categories: Categories data
            case_study: Case study packaging data
            battlecards: Supplier battlecards data
            extraction_timestamp: When the extraction was performed
            upsert: If True, update existing record for same client; if False, always insert
            
        Returns:
            Row ID of the inserted/updated record
        """
        if extraction_timestamp is None:
            extraction_timestamp = datetime.utcnow()
        
        # Convert dicts to JSON strings
        project_scope_json = json.dumps(project_scope, ensure_ascii=False, default=str)
        client_context_json = json.dumps(client_context, ensure_ascii=False, default=str)
        engagement_background_json = json.dumps(engagement_background, ensure_ascii=False, default=str)
        impact_json = json.dumps(impact, ensure_ascii=False, default=str)
        categories_json = json.dumps(categories, ensure_ascii=False, default=str)
        case_study_json = json.dumps(case_study, ensure_ascii=False, default=str)
        battlecards_json = json.dumps(battlecards, ensure_ascii=False, default=str)
        
        conn = self.connect()
        cursor = conn.cursor()
        
        try:
            if upsert:
                # Use MERGE for upsert
                sql = self.UPSERT_SQL.format(table_name=self.table_name)
                cursor.execute(
                    sql,
                    # For MERGE source
                    client_name,
                    # For UPDATE
                    extraction_timestamp,
                    project_scope_json,
                    client_context_json,
                    engagement_background_json,
                    impact_json,
                    categories_json,
                    case_study_json,
                    battlecards_json,
                    # For INSERT
                    client_name,
                    extraction_timestamp,
                    project_scope_json,
                    client_context_json,
                    engagement_background_json,
                    impact_json,
                    categories_json,
                    case_study_json,
                    battlecards_json,
                )
            else:
                # Simple INSERT
                sql = self.INSERT_SQL.format(table_name=self.table_name)
                cursor.execute(
                    sql,
                    client_name,
                    extraction_timestamp,
                    project_scope_json,
                    client_context_json,
                    engagement_background_json,
                    impact_json,
                    categories_json,
                    case_study_json,
                    battlecards_json,
                )
            
            conn.commit()
            
            # Get the ID of the affected row
            cursor.execute("SELECT @@IDENTITY")
            row = cursor.fetchone()
            row_id = row[0] if row else 0
            
            return row_id
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
    
    def get_client(self, client_name: str) -> Optional[dict]:
        """
        Retrieve extraction data for a client.
        
        Args:
            client_name: Name of the client to retrieve
            
        Returns:
            Dictionary with extraction data or None if not found
        """
        conn = self.connect()
        cursor = conn.cursor()
        
        sql = f"""
        SELECT 
            id,
            client_name,
            extraction_timestamp,
            project_scope,
            client_context,
            engagement_background,
            impact,
            categories,
            case_study,
            battlecards,
            created_at,
            updated_at
        FROM {self.table_name}
        WHERE client_name = ?
        ORDER BY extraction_timestamp DESC
        """
        
        cursor.execute(sql, client_name)
        row = cursor.fetchone()
        cursor.close()
        
        if not row:
            return None
        
        return {
            "id": row[0],
            "client_name": row[1],
            "extraction_timestamp": row[2],
            "project_scope": json.loads(row[3]) if row[3] else {},
            "client_context": json.loads(row[4]) if row[4] else {},
            "engagement_background": json.loads(row[5]) if row[5] else {},
            "impact": json.loads(row[6]) if row[6] else {},
            "categories": json.loads(row[7]) if row[7] else {},
            "case_study": json.loads(row[8]) if row[8] else {},
            "battlecards": json.loads(row[9]) if row[9] else {},
            "created_at": row[10],
            "updated_at": row[11],
        }
    
    def list_clients(self) -> list[dict]:
        """
        List all clients in the database.
        
        Returns:
            List of dictionaries with client_name and extraction_timestamp
        """
        conn = self.connect()
        cursor = conn.cursor()
        
        sql = f"""
        SELECT 
            client_name,
            extraction_timestamp,
            updated_at
        FROM {self.table_name}
        ORDER BY client_name
        """
        
        cursor.execute(sql)
        rows = cursor.fetchall()
        cursor.close()
        
        return [
            {
                "client_name": row[0],
                "extraction_timestamp": row[1],
                "updated_at": row[2],
            }
            for row in rows
        ]
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False
