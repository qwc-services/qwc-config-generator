import argparse
from collections import OrderedDict
from datetime import datetime
import threading

from config_generator.config_generator import ConfigGenerator


class Logger():
    """Simple logger class"""
    def debug(self, msg):
        print("[%s] \033[36mDEBUG: %s\033[0m" % (self.timestamp(), msg))

    def info(self, msg):
        print("[%s] INFO: %s" % (self.timestamp(), msg))

    def warning(self, msg):
        print("[%s] \033[33mWARNING: %s\033[0m" % (self.timestamp(), msg))

    def warn(self, msg):
        self.warning(msg)

    def error(self, msg):
        print("[%s] \033[31mERROR: %s\033[0m" % (self.timestamp(), msg))

    def critical(self, msg):
        print("[%s] \033[91mCRITICAL: %s\033[0m" % (self.timestamp(), msg))

    def timestamp(self):
        return datetime.now()


print("QWC ConfigGenerator")

# parse arguments
parser = argparse.ArgumentParser()
parser.add_argument(
    'config_file', help="Path to ConfigGenerator config file",
)
parser.add_argument(
    "command", choices=['all', 'service_configs', 'permissions'],
    help="Generate service configs and/or permissions"
)
parser.add_argument(
    "--use_cached_project_metadata", choices=["0", "1", "false", "true"],
    help="Whether to use cached project metadata",
    default="false"
)
parser.add_argument(
    "--force_readonly_datasets", choices=["0", "1", "false", "true"],
    help="Whether to force read-only dataset permissions",
    default="false"
)
args = parser.parse_args()

# create logger
logger = Logger()

# create ConfigGenerator
use_cached_project_metadata = str(args.use_cached_project_metadata).lower() in ["1","true"]
force_readonly_datasets = str(args.force_readonly_datasets).lower() in ["1","true"]
generator = ConfigGenerator(args.config_file, logger, threading.Event(), use_cached_project_metadata, force_readonly_datasets)
if args.command == 'all':
    generator.write_configs()
    generator.write_permissions()
elif args.command == 'service_configs':
    generator.write_configs()
elif args.command == 'permissions':
    generator.write_permissions()
generator.cleanup_temp_dir()
