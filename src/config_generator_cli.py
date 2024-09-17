import argparse
from collections import OrderedDict
from datetime import datetime
import json
import os

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
    help="generate service configs and/or permissions"
)
args = parser.parse_args()

# read ConfigGenerator config file
try:
    with open(args.config_file, encoding='utf-8') as f:
        # parse config JSON with original order of keys
        config = json.load(f, object_pairs_hook=OrderedDict)
except Exception as e:
    print("Error loading ConfigGenerator config:\n%s" % e)
    exit(1)

# create logger
logger = Logger()

# create ConfigGenerator
generator = ConfigGenerator(config, logger, os.path.dirname(args.config_file), False, False)
if args.command == 'all':
    generator.write_configs()
    generator.write_permissions()
elif args.command == 'service_configs':
    generator.write_configs()
elif args.command == 'permissions':
    generator.write_permissions()
generator.cleanup_temp_dir()
