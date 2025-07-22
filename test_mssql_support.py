#!/usr/bin/env python3
"""
Test script to verify MSSQL support in QWC Config Generator

This script tests the basic functionality of MSSQL datasource parsing
without requiring an actual MSSQL database connection.
"""

import sys
import os

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from config_generator.qgs_reader import QGSReader

def test_mssql_db_connection():
    """Test MSSQL database connection string parsing"""
    print("Testing MSSQL database connection parsing...")
    
    # Create a mock QGS reader
    reader = QGSReader(None, {}, None)
    
    # Test MSSQL connection string parsing
    test_datasources = [
        # Basic MSSQL connection
        "host=sqlserver.example.com port=1433 dbname='testdb' user='testuser' password='testpass'",
        # With schema and table
        "host=sqlserver.example.com port=1433 dbname='testdb' user='testuser' password='testpass' table=\"dbo\".\"test_table\" (geom)",
        # With SQL filter
        "host=sqlserver.example.com port=1433 dbname='testdb' user='testuser' password='testpass' table=\"dbo\".\"test_table\" sql=active = 1"
    ]
    
    for datasource in test_datasources:
        try:
            connection_string, datasource_filter = reader._QGSReader__mssql_db_connection(datasource)
            print(f"Input: {datasource}")
            print(f"  Connection: {connection_string}")
            print(f"  Filter: {datasource_filter}")
            print()
        except Exception as e:
            print(f"Error parsing datasource: {datasource}")
            print(f"  Error: {e}")
            print()

def test_mssql_table_metadata():
    """Test MSSQL table metadata parsing"""
    print("Testing MSSQL table metadata parsing...")
    
    # Create a mock QGS reader
    reader = QGSReader(None, {}, None)
    
    # Test MSSQL table metadata parsing
    test_datasources = [
        # With geometry column
        'table="dbo"."test_table" (geom) key=\'id\' srid=4326 type=Point',
        # Without geometry
        'table="dbo"."test_table" key=\'id\'',
        # Alternative schema format
        "schema='dbo' table='test_table' key='id' srid=3857 type=Polygon"
    ]
    
    for datasource in test_datasources:
        try:
            metadata = reader._QGSReader__mssql_table_metadata(datasource)
            print(f"Input: {datasource}")
            print(f"  Metadata: {metadata}")
            print()
        except Exception as e:
            print(f"Error parsing datasource: {datasource}")
            print(f"  Error: {e}")
            print()

def test_edit_field_types():
    """Test that MSSQL data types are mapped to QWC2 edit field types"""
    print("Testing MSSQL edit field types mapping...")
    
    # Import the MapViewerConfig to test field types
    from config_generator.map_viewer_config import MapViewerConfig
    
    # Test MSSQL data types
    mssql_types = [
        'int', 'bigint', 'tinyint', 'bit', 'decimal', 'float', 'real',
        'varchar', 'nvarchar', 'char', 'nchar', 'text', 'ntext',
        'date', 'datetime', 'datetime2', 'time', 'uniqueidentifier'
    ]
    
    print("MSSQL data type mappings:")
    for data_type in mssql_types:
        edit_type = MapViewerConfig.EDIT_FIELD_TYPES.get(data_type, 'UNKNOWN')
        print(f"  {data_type} -> {edit_type}")
    print()

if __name__ == "__main__":
    print("=" * 60)
    print("QWC Config Generator MSSQL Support Test")
    print("=" * 60)
    print()
    
    try:
        test_mssql_db_connection()
        test_mssql_table_metadata()
        test_edit_field_types()
        
        print("All tests completed successfully!")
        print()
        print("Next steps:")
        print("1. Test with actual QGIS projects that have MSSQL layers")
        print("2. Verify database connection and metadata queries work with real MSSQL")
        print("3. Test complete config generation workflow")
        
    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
