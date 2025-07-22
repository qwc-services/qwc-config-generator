# MSSQL Support Extension for QWC Config Generator

## Overview

Based on the review of the MSSQL support PR for qwc-data-service ([PR #40](https://github.com/qwc-services/qwc-data-service/pull/40/)), I have extended the QWC Config Generator to support MSSQL datasources alongside the existing PostgreSQL support.

## Changes Made

### 1. Updated QGS Reader (`src/config_generator/qgs_reader.py`)

#### Added MSSQL Provider Support
- Extended `layer_metadata()` method to handle `mssql` provider type
- Added `__mssql_db_connection()` method to parse MSSQL connection strings
- Added `__mssql_table_metadata()` method to parse MSSQL table metadata
- Updated `pg_layers()` method to include both PostgreSQL and MSSQL layers

#### Key Features:
- **Connection String Parsing**: Handles MSSQL connection parameters including:
  - Host/server, port, database name
  - User credentials with proper escaping
  - ODBC driver specification (defaults to "ODBC Driver 17 for SQL Server")
  - SQL filters
  - Builds proper SQLAlchemy MSSQL connection strings: `mssql+pyodbc://user:password@server:port/database?driver=...`

- **Table Metadata Parsing**: Supports multiple MSSQL datasource formats:
  - Standard format: `table="schema"."table_name" (geometry_column)`
  - Alternative format: `schema='schema' table='table_name'`
  - Extracts primary key, geometry type, and SRID information

#### Updated Database Queries
- Modified `__query_column_metadata()` method to handle both PostgreSQL and MSSQL dialects
- Uses dialect detection to choose appropriate SQL queries:
  - PostgreSQL: Uses `information_schema.columns` with fallback to `pg_catalog` queries
  - MSSQL: Uses `INFORMATION_SCHEMA.COLUMNS`

#### Enhanced Data Type Constraints
- Updated constraint logic to handle MSSQL-specific data types:
  - String types: `char`, `varchar`, `nchar`, `nvarchar`
  - Numeric types: `decimal`, `int`, `tinyint`
  - Proper handling of character length and numeric precision/scale

### 2. Updated Map Viewer Config (`src/config_generator/map_viewer_config.py`)

#### Extended Edit Field Types
Added comprehensive MSSQL data type mappings to `EDIT_FIELD_TYPES`:

**MSSQL Data Types Supported:**
- **Boolean**: `bit` → `boolean`
- **Integer**: `tinyint`, `int`, `bigint` → `number`
- **Decimal**: `decimal`, `money`, `smallmoney`, `float`, `real` → `number`
- **String**: `char`, `varchar`, `nchar`, `nvarchar`, `ntext` → `text`
- **Date/Time**: `date`, `datetime`, `datetime2`, `smalldatetime`, `datetimeoffset` → `date`
- **Time**: `time` → `time`
- **UUID**: `uniqueidentifier` → `text`

## Testing

Created comprehensive test scripts to verify MSSQL support:

### Test Results
- ✅ MSSQL connection string parsing
- ✅ Table metadata extraction
- ✅ Data type mappings
- ✅ Constraint handling

Example successful parsing:
```
Input: host=sqlserver.example.com port=1433 dbname='testdb' user='testuser' password='testpass'
Connection: mssql+pyodbc://testuser:testpass@sqlserver.example.com:1433/testdb?driver=ODBC%20Driver%2017%20for%20SQL%20Server

Input: table="dbo"."test_table" (geom) key='id' srid=4326 type=Point
Metadata: {'schema': 'dbo', 'table_name': 'test_table', 'geometry_column': 'geom', 'primary_key': 'id', 'geometry_type': 'POINT', 'srid': 4326}
```

## Integration with qwc-data-service

The config-generator changes align with the qwc-data-service MSSQL PR architecture:

1. **Database Abstraction**: Config-generator now generates proper database connection strings for both PostgreSQL and MSSQL
2. **Data Type Mapping**: Field type mappings ensure compatibility with the provider factory pattern
3. **Metadata Generation**: Proper schema, table, and column metadata extraction for MSSQL sources

## Deployment Considerations

### Dependencies
For MSSQL support, ensure the following are installed:
- `pyodbc>=4.0.30` (Python MSSQL driver)
- Microsoft ODBC Driver 17 for SQL Server

### Docker Support
Following the qwc-data-service pattern, consider creating:
- `Dockerfile.mssql` with MSSQL ODBC drivers
- Optional dependency management for MSSQL support

### Configuration
The config-generator will automatically detect and handle MSSQL datasources when:
1. QGIS project contains layers with `provider="mssql"`
2. Proper MSSQL connection parameters are provided in the datasource URI
3. Database is accessible with provided credentials

## Limitations and Future Improvements

### Current Limitations
1. **Geometry Support**: Assumes similar spatial function support as PostGIS (may need adjustment for SQL Server spatial types)
2. **Connection Testing**: No validation of MSSQL connections during config generation
3. **Error Handling**: Basic error handling for connection/metadata failures

### Future Enhancements
1. **Spatial Adapter**: Implement MSSQL-specific spatial function handling (similar to qwc-data-service spatial adapter)
2. **Connection Validation**: Add optional connection testing during config generation
3. **Advanced Features**: Support for MSSQL-specific features like schemas, collations, etc.
4. **Performance**: Optimize metadata queries for large MSSQL schemas

## Next Steps

1. **Integration Testing**: Test with actual QGIS projects containing MSSQL layers
2. **End-to-End Validation**: Verify complete workflow from QGIS project → config generation → qwc-data-service
3. **Documentation**: Update configuration documentation to include MSSQL examples
4. **CI/CD**: Add MSSQL support to testing pipeline if applicable

## Compatibility

- ✅ Backward compatible with existing PostgreSQL support
- ✅ No changes to public APIs
- ✅ Maintains existing configuration format
- ✅ Works with existing permission and resource management

The implementation ensures that existing PostgreSQL-based configurations continue to work unchanged while adding comprehensive MSSQL support through the same configuration mechanisms.
