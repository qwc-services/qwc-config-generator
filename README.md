[![](https://github.com/qwc-services/qwc-config-generator/workflows/build/badge.svg)](https://github.com/qwc-services/qwc-config-generator/actions)
[![docker](https://img.shields.io/docker/v/sourcepole/qwc-config-generator?label=Docker%20image&sort=semver)](https://hub.docker.com/r/sourcepole/qwc-config-generator)

QWC ConfigGenerator
====================

Generates JSON files for service configs and permissions from WMS GetCapabilities, QGS projects and QWC ConfigDB.

**This service is integrated into `qwc-docker`, consult [qwc-services.github.io](https://qwc-services.github.io/) for the general `qwc-services` documentation.**


Setup
-----

Create a ConfigGenerator config file `tenantConfig.json` below `INPUT_CONFIG_PATH` (see below) for each tenant.


Configuration
-------------

* [JSON schema](schemas/qwc-config-generator.json)
* [Example `tenantConfig.json`](https://github.com/qwc-services/qwc-docker/blob/master/volumes/config-in/default/tenantConfig.json)


*NOTE:* the Search service configuration takes its resources directly from the ConfigGenerator configuration. Its Permissions are collected from the ConfigDB (`solr_facet` resources), unless they are defined in the ConfigGenerator configuration.


### Schema validation

By default, the ConfigGenerator will validate the service configurations in `tenantConfig.json` against the schema definition of the service. The JSON Schemas are loaded from local files in `JSON_SCHEMAS_PATH`, or else downloaded from https://github.com/qwc-services/ if no schema files are present. You can disable the schema validation by setting `"validate_schema": false` in the ConfigGenerator's `config` block in `tenantConfig.json`.

### Custom resource types

If you want to define custom resource types for a custom service, you can add a record for the resource type to the configdb

    INSERT INTO qwc_config.resource_types(name, description, list_order) values ('<resource_name>', '<resource_description>', <list_order>);

and then add it to the `custom_resource_types` setting.

### Additional services

For any additional service (without specific resources), ConfigGenerator generates the configuration in `OUTPUT_CONFIG_PATH` directory.

Add the following configuration and adapt it to your service in `tenantConfig.json`:

```json
{
    "name": "<service_name>",
    "schema_url": "<service_schema_url>",
    "config": {...}
}
```

*Note*: `service_name` is expected to be camel case (i.e. `adminGui`), and the service name in the generated config will lowercase and hyphenated (i.e. `admin-gui`).

Usage
-----

### Script

Show command options:

    uv run src/config_generator_cli.py --help

Generate both service configs and permissions:

    uv run src/config_generator_cli.py ./tenantConfig.json all

Generate service config files:

    uv run src/config_generator_cli.py ./tenantConfig.json service_configs

Generate permissions file:

    uv run src/config_generator_cli.py ./tenantConfig.json permissions

### Service

Set the `INPUT_CONFIG_PATH` environment variable to the base directory where for the configuration files are that should be read by the ConfigGenerator (default: `config-in/`).
Set the `OUTPUT_CONFIG_PATH` environment variable to the base directory where the ConfigGenerator should output service configurations and permissions (default: `/tmp/`).

Base URL:

    http://localhost:5010/

Generate both service configs and permissions for `default` tenant:

    curl -X POST "http://localhost:5010/generate_configs?tenant=default"

### Update JSON schemas

You can change the directory from where the ConfigGenerator reads its schemas via the `JSON_SCHEMAS_PATH` environment variable (default `/tmp/`).
You can change the versions of the schemas that the ConfigGenerator uses for verification inside [schema-versions.json](src/schema-versions.json).

Download JSON schemas:

    uv run src/download_json_schemas.py master

Docker usage
------------

See sample [docker-compose.yml](https://github.com/qwc-services/qwc-docker/blob/master/docker-compose-example.yml) of [qwc-docker](https://github.com/qwc-services/qwc-docker).


