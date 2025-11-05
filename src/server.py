from collections import OrderedDict
from concurrent.futures import CancelledError
import logging
import os
import queue
import threading
import time
import traceback
import uuid

from flask import Flask, jsonify, request, stream_with_context, Response
from flask_restx import Api, Resource

from config_generator.config_generator import ConfigGenerator


# Flask application
app = Flask(__name__)
api = Api(app, version='1.0', title='Config Generator API',
    description="""API for QWC Config Generator.""",
    default_label='Config generator operations', doc='/api/'
)

flask_debug = os.environ.get("FLASK_DEBUG", "0") == "1"
app.logger.setLevel(logging.DEBUG if flask_debug else logging.INFO)


active_tasks = {}


def config_generator(tenant, logger, cancelled_event, use_cached_project_metadata, force_readonly_datasets=False):
    """Create a ConfigGenerator instance.

    :param str tenant: Tenant ID
    """
    if tenant is None:
        msg = "No tenant selected"
        logger.critical(msg)
        return None

    config_in_path = os.environ.get('INPUT_CONFIG_PATH', 'config-in/').rstrip('/')
    config_file = os.path.join(config_in_path, tenant, 'tenantConfig.json')
    return ConfigGenerator(config_file, logger, cancelled_event, use_cached_project_metadata, force_readonly_datasets)


# routes
@api.route("/generate_configs", methods=['GET', 'POST'])
@api.param('tenant', 'The tenant to generate configs for')
@api.param('stream_response', 'Whether to wait and stream the config generator logs')
@api.param('use_cached_project_metadata', 'Whether to use cached project metadata')
@api.param('force_readonly_datasets', 'Whether to force read-only dataset permissions')
class GenerateConfigs(Resource):
    def get(self):
        return self.generate_configs()

    def post(self):
        return self.generate_configs()

    def generate_configs(self):
        """Generate service configs and permissions."""
        logger, logs = self.create_logger()
        task_id = str(uuid.uuid4())
        running_event = threading.Event()
        cancelled_event = threading.Event()
        active_tasks[task_id] = {
            "running_event": running_event, "cancelled_event": cancelled_event, "logs": logs
        }
        threading.Thread(target=self.config_generator_task, args=[
            request.args, logger, running_event, cancelled_event
        ]).start()

        if request.args.get("stream_response", "").lower() in ["1","true"]:
            return Response(
                stream_with_context(self.log_stream(task_id, logs, running_event)), mimetype='text/plain'
            )
        else:
            return {"task_id": task_id}

    def create_logger(self):
        logs = []
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
                logs.append(log_output + "\n")

        stream_handler = StreamingLogHandler()
        logger = logging.getLogger(str(uuid.uuid4()))
        logger.setLevel(app.logger.getEffectiveLevel())
        logger.addHandler(stream_handler)
        return logger, logs

    def log_stream(self, task_id, logs, running_event):
        start = 0
        yield '{"task_id": "%s"}\n' % task_id
        while running_event.is_set():
            part_logs = logs[start:]
            start += len(part_logs)
            yield "".join(part_logs)
            time.sleep(1)
        part_logs = logs[start:]
        yield "".join(part_logs)

    def config_generator_task(self, args, logger, running_event, cancelled_event):
        running_event.set()
        tenant = args.get("tenant")
        use_cached_project_metadata = str(args.get("use_cached_project_metadata", "")).lower() in ["1","true"]
        force_readonly_datasets = str(args.get("force_readonly_datasets", "")).lower() in ["1","true"]
        try:
            generator = config_generator(tenant, logger, cancelled_event, use_cached_project_metadata, force_readonly_datasets)
            generator.write_configs()
            generator.write_permissions()
            generator.cleanup_temp_dir()
        except CancelledError as e:
            logger.error("<b>Cancelled</b>")
        except Exception as e:
            logger.error("<b>Internal error: %s\n%s</b>" % (str(e), traceback.format_exc()))

        for handler in logger.handlers:
            handler.flush()
        running_event.clear()

@api.route("/generate_configs_status")
@api.param('task_id', 'The task ID')
class GenerateConfigsStatus(Resource):
    def get(self):
        """Query the status of an active generate_configs task."""
        task_id = request.args.get('task_id')
        start = int(request.args.get('start', '0'))
        if not task_id in active_tasks:
            return {"error": "Unknown task id"}, 400

        task = active_tasks[task_id]
        logs = task['logs'][start:]
        running = task["running_event"].is_set()
        if not running:
            del active_tasks[task_id]
        return {
            "logs": "".join(logs),
            "log_linecount": len(logs),
            "running": running
        }

@api.route("/generate_configs_cancel")
@api.param('task_id', 'The task ID')
class GenerateConfigsCancel(Resource):
    def get(self):
        """Cancel an active generate_configs task."""
        task_id = request.args.get('task_id')
        if not task_id in active_tasks:
            return {"error": "Unknown task id"}, 400

        task = active_tasks[task_id]
        task["cancelled_event"].set()

        return {"cancelled": True}

@api.route("/maps")
@api.param('tenant', 'The tenant for which to query maps')
class QueryMaps(Resource):
    def get(self):
        """Return list of map names from themesConfig."""
        try:
            # get maps from ConfigGenerator
            tenant = request.args.get('tenant')
            use_cached_project_metadata = str(request.args.get("use_cached_project_metadata", "")).lower() in ["1","true"]
            generator = config_generator(tenant, app.logger, threading.Event(), use_cached_project_metadata)
            maps = generator.maps()
            generator.cleanup_temp_dir()

            return maps
        except Exception as e:
            return {'error': str(e)}, 500


@api.route("/maps/<path:map_name>", methods=['GET'])
@api.param('tenant', 'The tenant for which to query map details')
class QueryMapDetails(Resource):
    def get(self, map_name):
        """Return details for a map (e.g. its layers) from capabilities."""
        try:
            # get maps from ConfigGenerator
            tenant = request.args.get('tenant')
            use_cached_project_metadata = str(request.args.get("use_cached_project_metadata", "")).lower() in ["1","true"]
            generator = config_generator(tenant, app.logger, threading.Event(), use_cached_project_metadata)
            map_details = generator.map_details(map_name)
            generator.cleanup_temp_dir()

            return map_details
        except Exception as e:
            return {'error': str(e)}, 500


@api.route("/resources", methods=['GET'])
@api.param('tenant', 'The tenant for which to query map details')
class QueryResources(Resource):
    def get(self):
        """Return details for all maps (e.g. their layers) from capabilities."""

        maps_details = []

        try:
            # get maps from ConfigGenerator
            tenant = request.args.get('tenant')
            use_cached_project_metadata = str(request.args.get("use_cached_project_metadata", "")).lower() in ["1","true"]
            generator = config_generator(tenant, app.logger, threading.Event(), use_cached_project_metadata)
            maps = generator.maps()
            for map_name in maps:
                maps_details.append(generator.map_details(
                    map_name, with_attributes=True))
            generator.cleanup_temp_dir()

            return maps_details
        except Exception as e:
            return {'error': str(e)}, 500


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
