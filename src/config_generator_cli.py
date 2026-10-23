import argparse
import threading
from datetime import datetime

from config_generator.config_generator import ConfigGenerator


class Logger:
    """Simple logger class"""
    def debug(self, msg):
        print(f"[{self.timestamp()}] \033[36mDEBUG: {msg}\033[0m")

    def info(self, msg):
        print(f"[{self.timestamp()}] INFO: {msg}")

    def warning(self, msg):
        print(f"[{self.timestamp()}] \033[33mWARNING: {msg}\033[0m")

    def warn(self, msg):
        self.warning(msg)

    def error(self, msg):
        print(f"[{self.timestamp()}] \033[31mERROR: {msg}\033[0m")

    def critical(self, msg):
        print(f"[{self.timestamp()}] \033[91mCRITICAL: {msg}\033[0m")

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
