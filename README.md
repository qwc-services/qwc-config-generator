QWC Config Generator
====================

Generate JSON files for service configs and permissions from a `themesConfig.json`, WMS GetCapabilities and QWC ConfigDB.


Setup
-----

Create a QWC2 themes config file `themesConfig.json` and a ConfigGenerator config file `configGeneratorConfig.json` for each tenant (see below).


Configuration
-------------

Example `configGeneratorConfig.json`:
```json
{
  "service": "config-generator",
  "config": {
    "tenant": "default",
    "qwc2_themes_config_file": "../qwc-docker/volumes/qwc2/themesConfig-example.json",
    "default_qgis_server_url": "http://localhost:8001/ows/",
    "config_db_url": "postgresql:///?service=qwc_configdb",
    "config_path": "../qwc-docker/demo-config/"
  },
  "services": [
    {
      "name": "ogc",
      "generator_config": {
        "wms_services": {
          "online_resources": {
            "service": "http://localhost:8088/ows/",
            "feature_info": "http://localhost:8088/ows/",
            "legend": "http://localhost:8088/ows/"
          }
        }
      },
      "config": {
        "default_qgis_server_url": "http://qwc-qgis-server/ows/"
      }
    },
    {
      "name": "mapViewer",
      "generator_config": {
        "qwc2_config": {
          "qwc2_config_file": "../qwc-docker/volumes/qwc2/config.json"
        }
      },
      "config": {
        "qwc2_path": "/qwc2/",
        "auth_service_url": "/auth/",
        "data_service_url": "/api/v1/data/",
        "#document_service_url": "/api/v1/document/",
        "elevation_service_url": "/elevation/",
        "#info_service_url": "/api/v1/featureinfo/",
        "#legend_service_url": "/api/v1/legend/",
        "mapinfo_service_url": "/api/v1/mapinfo/",
        "ogc_service_url": "/ows/",
        "permalink_service_url": "/api/v1/permalink/",
        "#print_service_url": "/api/v1/print/",
        "search_data_service_url": "/api/v1/data/",
        "search_service_url": "/api/v2/search/"
      }
    }
  ]
}
```

For a full example see [configGeneratorConfig-example.json](configGeneratorConfig-example.json).


Usage
-----

Show command options:

    python config_generator.py --help

Generate both service configs and permissions:

    python config_generator.py ./configGeneratorConfig.json all

Generate service config files:

    python config_generator.py ./configGeneratorConfig.json service_configs

Generate permissions file:

    python config_generator.py ./configGeneratorConfig.json permissions


Development
-----------

Create a virtual environment:

    virtualenv --python=/usr/bin/python3 .venv

Activate virtual environment:

    source .venv/bin/activate

Install requirements:

    pip install -r requirements.txt

Run Demo-DB and QGIS Server:

    cd ../qwc-docker && docker-compose up -d qwc-postgis qwc-qgis-server

Generate service configs and permissions for Docker:

    python config_generator.py ./configGeneratorConfig-example.json all
