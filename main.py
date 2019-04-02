import argparse
import threading
import logging
import time
import os

from google.protobuf import text_format

import scheduler
import worker_interface
from utils import logger
from utils import util_ops
from web import web_interface as wi
from protos import scheduler_config_pb2

# Parse CL arguments
parser = argparse.ArgumentParser()
parser.add_argument('--logdir',
                    help="Directory where all log files should be stored",
                    required=True)
parser.add_argument('--config',
                    help="Config file for the scheduler", required=True)
parser.add_argument('--public', action='store_true',
                    help='Whether to publish web server to the local network')
parser.add_argument('--port', help='The port to use for the web interface. '
                    'Defaults to 5000', type=int)

args = parser.parse_args()


def load_config(config_path):
  scheduler_config = scheduler_config_pb2.SchedulerConfig()
  with open(config_path, 'r') as f:
    text_format.Merge(f.read(), scheduler_config)

  return scheduler_config


def run():
  if not os.path.exists(args.logdir):
    raise ValueError("Invalid logdir.")
  if not os.path.exists(args.config):
    raise ValueError("Invalid config file.")

  web_port = args.port if args.port else 5000

  logger.init_logger(args.logdir)

  config = load_config(args.config)

  num_devices_per_worker = util_ops.get_num_devices()
  if num_devices_per_worker < 1:
    raise ValueError("There must be atleast one GPU.")

  # In hours, 0 for no limit
  experiment_time_limit = config.experiment_time_limit
  initial_tf_port = config.initial_tf_port
  # We could run up to one tf server per device on one worker, so we need to
  # have that many ports
  tf_ports = list(range(initial_tf_port,
                        initial_tf_port + num_devices_per_worker))
  hosts = config.host_addresses

  workers = dict()
  for host in hosts:
    workers[host] = worker_interface.WorkerInterface(
      host=host, tf_ports=tf_ports, num_devices=num_devices_per_worker,
      logdir=args.logdir, resource_folder=config.resource_folder,
      docker_resource_folder=config.docker_resource_folder)

  experiment_scheduler = scheduler.Scheduler(
    workers=workers,
    logdir=args.logdir, experiment_time_limit=experiment_time_limit,
    reorganize_experiments_interval=config.reorganize_experiments_interval)

  web_interface = wi.WebInterface(
    scheduler_ref=experiment_scheduler, resource_folder=config.resource_folder,
    docker_resource_folder=config.docker_resource_folder)

  public = args.public
  # Start web server thread
  web_thread = threading.Thread(target=web_interface.run,
                                args=(public, web_port))
  web_thread.daemon = True
  web_thread.start()
  logging.info('Web Interface Thread started.')

  # Specify updates per second
  ups = config.ups
  frame_time = 1.0 / ups
  t0 = time.time()
  t_accumulated = 0
  while True:
    t1 = time.time()
    t_accumulated += (t1 - t0)
    t0 = t1

    while t_accumulated > frame_time:
      t_accumulated -= frame_time
      experiment_scheduler.update()

    time.sleep(frame_time - t_accumulated)


if __name__ == '__main__':
  run()
