from collections import OrderedDict
import logging
import os
import queue
import threading
import traceback
import uuid

from flask import Flask, json, jsonify, request, stream_with_context, Response

from config_generator.config_generator import ConfigGenerator


# Flask application
app = Flask(__name__)


def config_generator(tenant, logger, use_cached_project_metadata, force_readonly_datasets=False):
    """Create a ConfigGenerator instance.

    :param str tenant: Tenant ID
    """
    if tenant is None:
        msg = "No tenant selected"
        logger.error(msg)
        raise Exception(msg)

    # read ConfigGenerator config file
    config_in_path = os.environ.get(
        'INPUT_CONFIG_PATH', 'config-in/'
    ).rstrip('/') + '/'
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
        logger.error(msg)
        raise Exception(msg)

    # create ConfigGenerator
    return ConfigGenerator(config, logger, config_file_dir, use_cached_project_metadata, force_readonly_datasets)


# routes
@app.route("/generate_configs", methods=['POST'])
def generate_configs():
    """Generate service configs and permissions."""
    log_queue = queue.Queue()
    class StreamingLogHandler(logging.Handler):
        def emit(self, record):
            # Log to main logger
            app.logger.log(record.levelno, record.msg)

            level = record.levelname.upper()
            if level == "CRITICAL":
                log_output = '<b style="color: red">CRITICAL: %s</b>' % str(record.msg)
            elif level == "ERROR":
                log_output = '<span style="color: red">ERROR: %s</span>' % str(record.msg)
            elif level == "WARNING":
                log_output = '<span style="color: orange">WARNING: %s</span>' % str(record.msg)
            else:
                log_output = level + ": " + str(record.msg)
            log_queue.put(log_output)

    stream_handler = StreamingLogHandler()
    logger = logging.getLogger(str(uuid.uuid4()))
    logger.setLevel(app.logger.getEffectiveLevel())
    logger.addHandler(stream_handler)

    config_generator_running = threading.Event()
    config_generator_running.set()

    def run_config_generator(args):
        tenant = args.get("tenant")
        use_cached_project_metadata = str(args.get("use_cached_project_metadata", "")).lower() in ["1","true"]
        force_readonly_datasets = str(args.get("force_readonly_datasets", "")).lower() in ["1","true"]
        generator = config_generator(tenant, logger, use_cached_project_metadata, force_readonly_datasets)
        try:
            generator.write_configs()
            generator.write_permissions()
            generator.cleanup_temp_dir()
        except Exception as e:
            logger.error("<b>Python Exception: %s\n%s</b>" % (str(e), traceback.format_exc()))

        config_generator_running.clear()

    threading.Thread(target=run_config_generator, args=[request.args]).start()

    def log_stream():
        while config_generator_running.is_set():
            try:
                # Wait for a log message (timeout avoids hanging)
                log = log_queue.get(timeout=1)
                yield log + "\n"
            except queue.Empty:
                pass

    return Response(stream_with_context(log_stream()), mimetype='text/plain')

@app.route("/maps", methods=['GET'])
def maps():
    """Return list of map names from themesConfig."""
    try:
        # get maps from ConfigGenerator
        tenant = request.args.get('tenant')
        use_cached_project_metadata = str(request.args.get("use_cached_project_metadata", "")).lower() in ["1","true"]
        generator = config_generator(tenant, app.logger, use_cached_project_metadata)
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
        use_cached_project_metadata = str(request.args.get("use_cached_project_metadata", "")).lower() in ["1","true"]
        generator = config_generator(tenant, app.logger, use_cached_project_metadata)
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
        use_cached_project_metadata = str(request.args.get("use_cached_project_metadata", "")).lower() in ["1","true"]
        generator = config_generator(tenant, app.logger, use_cached_project_metadata)
        maps = generator.maps()
        for map_name in maps:
            maps_details.append(generator.map_details(
                map_name, with_attributes=True))
        generator.cleanup_temp_dir()

        return jsonify(maps_details)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


""" readyness probe endpoint """
@app.route("/ready", methods=['GET'])
def ready():
    return jsonify({"status": "OK"})


""" liveness probe endpoint """
@app.route("/healthz", methods=['GET'])
def healthz():
    return jsonify({"status": "OK"})


# local webserver
if __name__ == '__main__':
    print("Starting ConfigGenerator service...")
    app.run(host='localhost', port=5010, debug=True)
