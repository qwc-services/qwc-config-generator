[![](https://github.com/qwc-services/qwc-config-generator/workflows/build/badge.svg)](https://github.com/qwc-services/qwc-config-generator/actions)
[![](https://img.shields.io/docker/pulls/sourcepole/qwc-config-generator)](https://hub.docker.com/r/sourcepole/qwc-config-generator)

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
    "config_path": "../qwc-docker/demo-config/",
    "permissions_default_allow": true
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

For a full example see [configGeneratorConfig-example.json](configGeneratorConfig-example.json).

*NOTE:* the Search service config takes its resources and permissions directly from the ConfigGenerator config

*NOTE:* the FeatureInfo service config may take additional WMS service resources and permissions directly from the ConfigGenerator config, e.g. for external info layers:

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

Show command options:

    python config_generator_cli.py --help

Generate both service configs and permissions:

    python config_generator_cli.py ./configGeneratorConfig.json all

Generate service config files:

    python config_generator_cli.py ./configGeneratorConfig.json service_configs

Generate permissions file:

    python config_generator_cli.py ./configGeneratorConfig.json permissions


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

    python config_generator_cli.py ./configGeneratorConfig-example.json all
