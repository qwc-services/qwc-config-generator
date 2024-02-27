from collections import OrderedDict
import os
import traceback

from flask import Flask, json, jsonify, request

from config_generator.config_generator import ConfigGenerator


# Flask application
app = Flask(__name__)

config_in_path = os.environ.get(
    'INPUT_CONFIG_PATH', 'config-in/'
).rstrip('/') + '/'


def config_generator(tenant):
    """Create a ConfigGenerator instance.

    :param str tenant: Tenant ID
    """
    if tenant is None:
        msg = "No tenant selected"
        app.logger.error(msg)
        raise Exception(msg)

    # read ConfigGenerator config file
    config_file_dir = os.path.join(config_in_path, tenant)
    try:
        config_file = os.path.join(
            config_file_dir, 'tenantConfig.json'
        )
        with open(config_file, encoding='utf-8') as f:
            # parse config JSON with original order of keys
            config = json.load(f, object_pairs_hook=OrderedDict)
    except Exception as e:
        msg = "Error loading ConfigGenerator config:\n%s" % e
        app.logger.error(msg)
        raise Exception(msg)

    # create ConfigGenerator
    return ConfigGenerator(config, app.logger, config_file_dir)


# routes
@app.route("/generate_configs", methods=['POST'])
def generate_configs():
    """Generate service configs and permissions."""
    log_output = ""
    try:
        # create ConfigGenerator
        tenant = request.args.get("tenant")
        generator = config_generator(tenant)
        generator.write_configs()
        generator.write_permissions()
        generator.cleanup_temp_dir()
        logger = generator.get_logger()

        for entry in logger.log_entries():
            level = entry["level"].upper()
            if level == "CRITICAL":
                log_output += '<b style="color: red">CRITICAL: %s</b>\n' % str(entry["msg"])
            elif level == "ERROR":
                log_output += '<span style="color: red">ERROR: %s</span>\n' % str(entry["msg"])
            elif level == "WARNING":
                log_output += '<span style="color: orange">WARNING: %s</span>\n' % str(entry["msg"])
            else:
                log_output += level + ": " + str(entry["msg"]) + "\n"

        return (log_output, 200)
    except Exception as e:
        return (log_output + "\n\nPython Exception: " + str(e) + "\n" + traceback.format_exc(), 500)


@app.route("/maps", methods=['GET'])
def maps():
    """Return list of map names from themesConfig."""
    try:
        # get maps from ConfigGenerator
        tenant = request.args.get('tenant')
        generator = config_generator(tenant)
        maps = generator.maps()
        generator.cleanup_temp_dir()

        return jsonify(maps)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/maps/<path:map_name>", methods=['GET'])
def map_details(map_name):
    """Return details for a map (e.g. its layers) from capabilities."""
    try:
        # get maps from ConfigGenerator
        tenant = request.args.get('tenant')
        generator = config_generator(tenant)
        map_details = generator.map_details(map_name)
        generator.cleanup_temp_dir()

        return jsonify(map_details)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/resources", methods=['GET'])
def resources():
    """Return details for all maps (e.g. their layers) from capabilities."""

    maps_details = []

    try:
        # get maps from ConfigGenerator
        tenant = request.args.get('tenant')
        generator = config_generator(tenant)
        maps = generator.maps()
        for map_name in maps:
            maps_details.append(generator.map_details(
                map_name, with_attributes=True))
        generator.cleanup_temp_dir()

        return jsonify(maps_details)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# local webserver
if __name__ == '__main__':
    print("Starting ConfigGenerator service...")
    app.run(host='localhost', port=5010, debug=True)
