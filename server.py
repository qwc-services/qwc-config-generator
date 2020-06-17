from collections import OrderedDict
import os

from flask import Flask, json, request

from config_generator.config_generator import ConfigGenerator


# Flask application
app = Flask(__name__)

# get path to ConfigGenerator config file
config_file = os.environ.get(
    'CONFIG_GENERATOR_CONFIG', 'configGeneratorConfig.json'
)

config_in_path = os.environ.get(
    'INPUT_CONFIG_PATH', 'config-in/'
)


def config_generator():
    """Create a ConfigGenerator instance."""
    # read ConfigGenerator config file
    try:
        with open(config_file) as f:
            # parse config JSON with original order of keys
            config = json.load(f, object_pairs_hook=OrderedDict)
    except Exception as e:
        msg = "Error loading ConfigGenerator config:\n%s" % e
        app.logger.error(msg)
        raise Exception(msg)

    # create ConfigGenerator
    return ConfigGenerator(config, app.logger)


# routes
@app.route("/generate_configs", methods=['POST'])
def generate_configs():
    """Generate service configs and permissions."""
    tenant_name = request.args.get("tenant")

    if tenant_name:
        global config_file
        config_file = os.path.join(
            config_in_path,
            tenant_name,
            "configGeneratorConfig.json")

    try:
        # create ConfigGenerator
        generator = config_generator()
        generator.write_configs()
        generator.write_permissions()
        logger = generator.get_logger()

        log_output = ""
        for entry in logger.log_entries():
            log_output += entry["level"].upper() + ": " + \
                          str(entry["msg"]) + "\n"

        return (log_output, 200)
    except Exception as e:
        return (log_output + "\n\nPython Exception: " + str(e), 500)

    finally:
        config_file = os.environ.get(
            'CONFIG_GENERATOR_CONFIG', 'configGeneratorConfig.json')


# local webserver
if __name__ == '__main__':
    print("Starting ConfigGenerator service...")
    app.run(host='localhost', port=5010, debug=True)
