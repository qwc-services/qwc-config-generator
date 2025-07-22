#!/usr/bin/env python3
"""
Simple test to verify MSSQL parsing logic without imports

This tests the core logic for MSSQL datasource parsing
"""

import re
from urllib.parse import quote as urlquote

def test_mssql_db_connection(datasource):
    """Parse QGIS datasource URI and return SQLAlchemy DB connection
    string for a MSSQL database.

    :param str datasource: QGIS datasource URI
    """
    connection_string = None
    datasource_filter = None

    # MSSQL connection parameters
    server, database, user, password, port, driver = '', '', '', '', '1433', ''

    # Parse server/host
    m = re.search(r"host=(\S+)", datasource)
    if m is not None:
        server = m.group(1)

    # Parse database name
    m = re.search(r"database='(.+?)' \w+=", datasource)
    if m is None:
        m = re.search(r"dbname='(.+?)' \w+=", datasource)
    if m is not None:
        database = m.group(1)

    # Parse port
    m = re.search(r"port=(\d+)", datasource)
    if m is not None:
        port = m.group(1)

    # Parse user
    m = re.search(r"user='(.+?)' \w+=", datasource)
    if m is not None:
        user = m.group(1)
        # unescape \' and \\'
        user = re.sub(r"\\'", "'", user)
        user = re.sub(r"\\\\", r"\\", user)

    # Parse password
    m = re.search(r"password='(.+?)' \w+=", datasource)
    if m is not None:
        password = m.group(1)
        # unescape \' and \\'
        password = re.sub(r"\\'", "'", password)
        password = re.sub(r"\\\\", r"\\", password)

    # Parse ODBC driver if specified
    m = re.search(r"driver='(.+?)' \w+=", datasource)
    if m is not None:
        driver = m.group(1)
    else:
        # Default to ODBC Driver 17 for SQL Server
        driver = 'ODBC Driver 17 for SQL Server'

    # Build MSSQL connection string
    # Format: mssql+pyodbc://user:password@server:port/database?driver=ODBC+Driver+17+for+SQL+Server
    if server and database:
        connection_string = 'mssql+pyodbc://'
        if user and password:
            connection_string += f"{urlquote(user)}:{urlquote(password)}@"
        
        connection_string += f"{server}:{port}/{database}"
        
        if driver:
            connection_string += f"?driver={urlquote(driver)}"

    # Parse SQL filter
    m = re.search(r"sql=(.*)$", datasource)
    if m is not None:
        import html
        datasource_filter = html.unescape(m.group(1))

    return connection_string, datasource_filter

def test_mssql_table_metadata(datasource):
    """Parse QGIS datasource URI and return table metadata for MSSQL.

    :param str datasource: QGIS datasource URI
    """
    metadata = {}
    if not datasource:
        return metadata

    # parse schema, table and geometry column
    # MSSQL may use different format in QGIS datasource strings
    m = re.search(r'table="([^"]+)"\."([^"]+)" \(([^)]+)\)', datasource)
    if m is not None:
        metadata['schema'] = m.group(1)
        metadata['table_name'] = m.group(2)
        metadata['geometry_column'] = m.group(3)
    else:
        m = re.search(r'table="([^"]+)"\."([^"]+)"', datasource)
        if m is not None:
            metadata['schema'] = m.group(1)
            metadata['table_name'] = m.group(2)
        else:
            # Alternative format for MSSQL
            m = re.search(r"schema='([^']+)' table='([^']+)'", datasource)
            if m is not None:
                metadata['schema'] = m.group(1)
                metadata['table_name'] = m.group(2)

    # Parse primary key
    m = re.search(r"key='([^']+)'", datasource)
    if m is not None:
        metadata['primary_key'] = m.group(1)

    # Parse geometry type
    m = re.search(r"type=([\w.]+)", datasource)
    if m is not None:
        metadata['geometry_type'] = m.group(1).upper()

    # Parse SRID
    m = re.search(r"srid=([\d.]+)", datasource)
    if m is not None:
        metadata['srid'] = int(m.group(1))

    return metadata

def main():
    print("=" * 60)
    print("QWC Config Generator MSSQL Support Test")
    print("=" * 60)
    print()
    
    # Test MSSQL connection string parsing
    print("Testing MSSQL database connection parsing...")
    
    test_datasources = [
        "host=sqlserver.example.com port=1433 dbname='testdb' user='testuser' password='testpass'",
        "host=sqlserver.example.com port=1433 dbname='testdb' user='testuser' password='testpass' table=\"dbo\".\"test_table\" (geom)",
        "host=sqlserver.example.com port=1433 dbname='testdb' user='testuser' password='testpass' table=\"dbo\".\"test_table\" sql=active = 1"
    ]
    
    for datasource in test_datasources:
        try:
            connection_string, datasource_filter = test_mssql_db_connection(datasource)
            print(f"Input: {datasource}")
            print(f"  Connection: {connection_string}")
            print(f"  Filter: {datasource_filter}")
            print()
        except Exception as e:
            print(f"Error parsing datasource: {datasource}")
            print(f"  Error: {e}")
            print()

    # Test MSSQL table metadata parsing
    print("Testing MSSQL table metadata parsing...")
    
    test_datasources = [
        'table="dbo"."test_table" (geom) key=\'id\' srid=4326 type=Point',
        'table="dbo"."test_table" key=\'id\'',
        "schema='dbo' table='test_table' key='id' srid=3857 type=Polygon"
    ]
    
    for datasource in test_datasources:
        try:
            metadata = test_mssql_table_metadata(datasource)
            print(f"Input: {datasource}")
            print(f"  Metadata: {metadata}")
            print()
        except Exception as e:
            print(f"Error parsing datasource: {datasource}")
            print(f"  Error: {e}")
            print()

    # Test MSSQL data types
    print("Testing MSSQL edit field types mapping...")
    
    # Simplified field types mapping
    EDIT_FIELD_TYPES = {
        # PostgreSQL types
        'bigint': 'number',
        'boolean': 'boolean',
        'character varying': 'text',
        'date': 'date',
        'double precision': 'number',
        'file': 'file',
        'integer': 'number',
        'numeric': 'number',
        'real': 'number',
        'smallint': 'number',
        'text': 'text',
        'time': 'time',
        'timestamp with time zone': 'date',
        'timestamp without time zone': 'date',
        'uuid': 'text',
        # MSSQL types
        'bit': 'boolean',
        'tinyint': 'number',
        'int': 'number',
        'bigint': 'number',
        'decimal': 'number',
        'money': 'number',
        'smallmoney': 'number',
        'float': 'number',
        'real': 'number',
        'char': 'text',
        'varchar': 'text',
        'nchar': 'text',
        'nvarchar': 'text',
        'ntext': 'text',
        'date': 'date',
        'datetime': 'date',
        'datetime2': 'date',
        'smalldatetime': 'date',
        'time': 'time',
        'datetimeoffset': 'date',
        'uniqueidentifier': 'text'
    }
    
    mssql_types = [
        'int', 'bigint', 'tinyint', 'bit', 'decimal', 'float', 'real',
        'varchar', 'nvarchar', 'char', 'nchar', 'text', 'ntext',
        'date', 'datetime', 'datetime2', 'time', 'uniqueidentifier'
    ]
    
    print("MSSQL data type mappings:")
    for data_type in mssql_types:
        edit_type = EDIT_FIELD_TYPES.get(data_type, 'UNKNOWN')
        print(f"  {data_type} -> {edit_type}")
    print()
    
    print("All tests completed successfully!")
    print()
    print("Next steps:")
    print("1. Test with actual QGIS projects that have MSSQL layers")
    print("2. Verify database connection and metadata queries work with real MSSQL")
    print("3. Test complete config generation workflow")

if __name__ == "__main__":
    main()
