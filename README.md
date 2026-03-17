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

### Environment variables

Config options in the config file can be overridden by equivalent uppercase environment variables.

In addition, the following environment variables are supported:

| Name                         | Default       | Description                                                                            |
|------------------------------|---------------|----------------------------------------------------------------------------------------|
| `INPUT_CONFIG_PATH`          | `config-in/`  | Base directory where the input configuration files are located.                        |
| `OUTPUT_CONFIG_PATH`         | `/tmp/`       | Base directory where generated service and permission configuration files are located. |
| `JSON_SCHEMAS_PATH`          | `/tmp/`       | Directory where service schemas are loaded.                                            |

### Schema validation

By default, the ConfigGenerator will validate the service configurations in `tenantConfig.json` against the schema definition of the service. The JSON Schemas are loaded from local files in `JSON_SCHEMAS_PATH`, or else downloaded from https://github.com/qwc-services/ if no schema files are present. You can disable the schema validation by setting `"validate_schema": false` in the ConfigGenerator's `config` block in `tenantConfig.json`.

You can change the versions of the schemas that the ConfigGenerator uses for verification inside [schema-versions.json](src/schema-versions.json).

A helper script to download the JSON schemas of all QWC services registered in `schema-versions.json` is available at [src/download_json_schemas.py](src/download_json_schemas.py).

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

### CLI interface

Show command options:

    uv run src/config_generator_cli.py --help

Generate both service configs and permissions:

    uv run src/config_generator_cli.py ./tenantConfig.json all

Generate service config files:

    uv run src/config_generator_cli.py ./tenantConfig.json service_configs

Generate permissions file:

    uv run src/config_generator_cli.py ./tenantConfig.json permissions

Additionally, the following command line args may be specified:

- `--use_cached_project_metadata=1`: Whether to use cached project metadata
- `--force_readonly_datasets=1`: Whether to force read-only dataset permissions

### Service interface

Install dependencies and run:

    # Setup venv
    uv venv .venv

    export INPUT_CONFIG_PATH=<INPUT_CONFIG_PATH>
    export OUTPUT_CONFIG_PATH=<INPUT_CONFIG_PATH>
    uv run src/server.py

Set `FLASK_DEBUG=1` for additional debug output.

Set `FLASK_RUN_PORT=<port>` to change the default port (default: `5000`).


Generate both service configs and permissions for `default` tenant:

    # Non-blocking call, returns task_id
    curl "http://localhost:5000/generate_configs?tenant=default"

    # Blocking call, streams log output
    curl "http://localhost:5000/generate_configs?tenant=default&stream_response=1"

Additionally, the following query parameters may be specified:

- `use_cached_project_metadata=1`: Whether to use cached project metadata
- `force_readonly_datasets=1`: Whether to force read-only dataset permissions

Watch config generator task status:

    curl "http://localhost:5000/generate_configs_status?task_id=<task_id>"

Cancel config generator task:

    curl "http://localhost:5000/generate_configs_cancel?task_id=<task_id>"

Docker usage
------------

The Docker image is published on [Dockerhub](https://hub.docker.com/r/sourcepole/qwc-config-generator).

See sample [docker-compose.yml](https://github.com/qwc-services/qwc-docker/blob/master/docker-compose-example.yml) of [qwc-docker](https://github.com/qwc-services/qwc-docker).
