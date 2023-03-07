import json
import os
import sys
import requests

from urllib.parse import urlparse


# get target path
json_schemas_path = os.environ.get('JSON_SCHEMAS_PATH', '/tmp/')
branch = sys.argv[1] if len(sys.argv) > 1 else 'master'

print(
    "Downloading JSON schemas for all QWC service configs to %s" %
    json_schemas_path
)

# load schema-versions.json
schema_versions = {}
schema_versions_path = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    f'schemas/schema-versions-{branch}.json'
)
try:
    with open(schema_versions_path) as f:
        schema_versions = json.load(f)
except Exception as e:
    print(
        "Error: Could not load JSON schema versions from %s:\n%s" %
        (schema_versions_path, e)
    )
    exit(1)

# download and save JSON schemas
for schema in schema_versions.get('schemas', []):
    try:
        # parse schema URL
        service = schema.get('service')
        schema_url = schema.get('schema_url', '')
        file_name = os.path.basename(urlparse(schema_url).path)
        file_path = os.path.join(json_schemas_path, file_name)

        # download JSON schema
        response = requests.get(schema_url)
        if response.status_code != requests.codes.ok:
            raise Exception(
                "Download error: Status %s\n%s..." %
                (response.status_code, response.text[0:150])
            )

        # save to file
        with open(file_path, 'wb') as f:
            f.write(response.content)
            print("Downloaded %s" % file_name)
    except Exception as e:
        print(
            "Error: Could not download JSON schema for service '%s' from %s\n"
            "%s" % (service, schema_url, e)
        )
