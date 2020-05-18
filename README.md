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
    "config_db_url": "postgresql:///?service=qwc_configdb",
    "config_path": "../qwc-docker/demo-config/"
  },
  "services": [
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
