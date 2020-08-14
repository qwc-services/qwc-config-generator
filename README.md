[![](https://github.com/qwc-services/qwc-config-generator/workflows/build/badge.svg)](https://github.com/qwc-services/qwc-config-generator/actions)
[![](https://img.shields.io/docker/pulls/sourcepole/qwc-config-generator)](https://hub.docker.com/r/sourcepole/qwc-config-generator)

QWC Config Generator
====================

Generate JSON files for service configs and permissions from WMS GetCapabilities, QGS projects and QWC ConfigDB.


Setup
-----

Create a ConfigGenerator config file `tenantConfig.json` for each tenant (see below).


Configuration
-------------

Example `tenantConfig.json`:
```json
{
  "$schema": "https://github.com/qwc-services/qwc-config-generator/raw/master/schemas/qwc-config-generator.json",
  "service": "config-generator",
  "config": {
    "tenant": "default",
    "config_db_url": "postgresql:///?service=qwc_configdb",
    "default_qgis_server_url": "http://localhost:8001/ows/",
    "qgis_projects_base_dir": "/data",
    "permissions_default_allow": true
  },
  "themesConfig": {
      "defaultScales": [100000000, 50000000, 25000000, 10000000, 4000000, 2000000, 1000000, 400000, 200000, 80000, 40000, 20000, 10000, 8000, 6000, 4000, 2000, 1000, 500, 250, 100],
      "defaultPrintGrid": [{"s": 10000000, "x": 1000000, "y": 1000000}, {"s": 1000000, "x": 100000, "y": 100000}, {"s": 100000, "x": 10000, "y": 10000}, {"s": 10000, "x": 1000, "y": 1000}, {"s": 1000, "x": 100, "y": 100}, {"s": 100, "x": 10, "y": 10}],
      "defaultWMSVersion":"1.3.0",
      "defaultBackgroundLayers": [],
      "defaultSearchProviders": ["coordinates"],
      "defaultMapCrs": "EPSG:3857",
      "themes": {
        "items": [
          {
            "title": "Demo",
            "url": "/ows/qwc_demo",
            "default": true,
            "attribution": "Demo attribution",
            "attributionUrl": "https://127.0.0.1/",
            "backgroundLayers": [
                {
                  "name": "bluemarble",
                  "printLayer": "bluemarble_bg",
                  "visibility": true
                },
                {
                  "name": "mapnik",
                  "printLayer": "osm_bg"
                }
            ],
            "searchProviders": ["coordinates"],
            "mapCrs": "EPSG:3857",
            "additionalMouseCrs": [],
            "extent": [-1000000, 4000000, 3000000, 8000000],
            "skipEmptyFeatureAttributes": true,
            "printResolutions": [300],
            "thumbnail": "default.jpg"
          }
        ],
        "backgroundLayers": [
          {
            "name": "mapnik",
            "title": "Open Street Map",
            "type": "osm",
            "source": "osm",
            "thumbnail": "mapnik.jpg",
            "attribution": "OpenStreetMap contributors",
            "attributionUrl": "https://www.openstreetmap.org/copyright"
          }
        ]
      }
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
          "qwc2_config_file": "../qwc-docker/volumes/qwc2/config.json",
          "qwc2_index_file": "../qwc-docker/volumes/qwc2/index.html"
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
    },
    {
      "name": "featureInfo",
      "config": {
        "default_qgis_server_url": "http://qwc-qgis-server/ows/"
      }
    },
    {
      "name": "search",
      "config": {
        "solr_service_url": "http://qwc-solr:8983/solr/gdi/select",
        "search_result_limit": 50,
        "db_url": "postgresql:///?service=qwc_geodb"
      },
      "resources": {
        "facets": [
          {
            "name": "background",
            "filter_word": "Background"
          },
          {
            "name": "foreground",
            "filter_word": "Map"
          },
          {
            "name": "ne_10m_admin_0_countries",
            "filter_word": "Country",
            "table_name": "qwc_geodb.search_v",
            "geometry_column": "geom",
            "facet_column": "subclass"
          }
        ]
      },
      "permissions": [
        {
          "role": "public",
          "permissions": {
            "dataproducts": [
              "qwc_demo"
            ],
            "solr_facets": [
              "foreground",
              "ne_10m_admin_0_countries"
            ]
          }
        }
      ]
    }
  ]
}
```

For a full example see [tenantConfig-example.json](tenantConfig-example.json) ([JSON schema](schemas/qwc-config-generator.json)).

*NOTE:* the QWC2 themes config is defined under `themesConfig` in the ConfigGenerator config and not in a separate file.

QGIS projects can be automatically detected when `qgis_projects_scan_base_dir` is defined.
For adding these projects, the following settings need to be defined in `themesConfig`.

- `defaultBackgroundLayers`
- `defaultSearchProviders`
- `defaultMapCrs`

*NOTE:* The Search service config takes its resources directly from the ConfigGenerator config. Its Permissions are collected from the ConfigDB (`solr_facet` resources), unless they are defined in the ConfigGenerator config.

*NOTE:* the FeatureInfo service config may take additional WMS service resources and permissions directly from the ConfigGenerator config, e.g. for external info layers. Its Permissions are collected from the ConfigDB (`feature_info_service`, `feature_info_layer` resources), unless they are defined in the ConfigGenerator config. Example:

```json
    {
      "name": "featureInfo",
      "config": {
        "default_qgis_server_url": "http://qwc-qgis-server/ows/"
      },
      "resources": {
        "wms_services": [
          {
            "name": "external_info_layers",
            "root_layer": {
              "name": "external_info_layers",
              "layers": [
                {
                  "name": "example_info_layer",
                  "title": "External info layer",
                  "attributes": [
                    {
                      "name": "name"
                    },
                    {
                      "name": "geometry"
                    }
                  ],
                  "info_template": {
                    "type": "wms",
                    "wms_url": "https://example.com/wms/demo"
                  }
                }
              ]
            }
          }
        ]
      },
      "permissions": [
        {
          "role": "public",
          "permissions": {
            "wms_services": [
              {
                "name": "external_info_layers",
                "layers": [
                  {
                    "name": "external_info_layers"
                  },
                  {
                    "name": "example_info_layer",
                    "attributes": ["name", "geometry"],
                    "info_template": true
                  }
                ]
              }
            ]
          }
        }
      ]
    }
```

### Permissions

Using the `permissions_default_allow` setting, some resources can be set to be permitted or restricted by default if no permissions are set (default: `true`). Affected resources are `map`, `layer`, `print_template` and `viewer_task`.

* i.e. `permissions_default_allow: true`: all maps, layers and attributes are permitted by default
* i.e. `permissions_default_allow: false`: maps and layers are only available if their resources and permissions are explicitly configured; though attributes are still permitted by default


Usage
-----

### Script

Show command options:

    python config_generator_cli.py --help

Generate both service configs and permissions:

    python config_generator_cli.py ./tenantConfig.json all

Generate service config files:

    python config_generator_cli.py ./tenantConfig.json service_configs

Generate permissions file:

    python config_generator_cli.py ./tenantConfig.json permissions

### Service

Set the `INPUT_CONFIG_PATH` environment variable to the base dir for reading generator config files (default: `config-in/`).
Set the `OUTPUT_CONFIG_PATH` environment variable to the base dir for writing service configs and permissions (default: `/tmp/`).

*NOTE:* Requires write permissions for config-generator docker user (`www-data`) in `OUTPUT_CONFIG_PATH` for writing service configs and permissions.

Base URL:

    http://localhost:5010/

Generate both service configs and permissions for `default` tenant:

    curl -X POST "http://localhost:5010/generate_configs?tenant=default"


Development
-----------

Create a virtual environment:

    virtualenv --python=/usr/bin/python3 --system-site-package .venv

Activate virtual environment:

    source .venv/bin/activate

Install requirements (*NOTE:* additionally requires modules from `python-qgis`):

    pip install -r requirements.txt

Run Demo-DB and QGIS Server:

    cd ../qwc-docker && docker-compose up -d qwc-postgis qwc-qgis-server

Generate service configs and permissions for Docker:

    python config_generator_cli.py ./tenantConfig-example.json all
