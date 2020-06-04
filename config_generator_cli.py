import argparse
from collections import OrderedDict
import json

from config_generator.config_generator import ConfigGenerator, Logger


print("QWC ConfigGenerator")

# parse arguments
parser = argparse.ArgumentParser()
parser.add_argument(
    'config_file', help="Path to ConfigGenerator config file"
)
parser.add_argument(
    "command", choices=['all', 'service_configs', 'permissions'],
    help="generate service configs and/or permissions"
)
args = parser.parse_args()

# read ConfigGenerator config file
try:
    with open(args.config_file) as f:
        # parse config JSON with original order of keys
        config = json.load(f, object_pairs_hook=OrderedDict)
except Exception as e:
    print("Error loading ConfigGenerator config:\n%s" % e)
    exit(1)

# create logger
logger = Logger()

# create ConfigGenerator
generator = ConfigGenerator(config, logger)
if args.command == 'all':
    generator.write_configs()
    generator.write_permissions()
elif args.command == 'service_configs':
    generator.write_configs()
elif args.command == 'permissions':
    generator.write_permissions()
