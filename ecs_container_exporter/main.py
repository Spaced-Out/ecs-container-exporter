#!/usr/bin/env python3
import sys
import time
import click
import signal
import requests
from requests.compat import urljoin

from prometheus_client import start_http_server
from prometheus_client.core import REGISTRY

from ecs_container_exporter.utils import create_metric, task_metric_tags, create_prometheus_metric, init_statsd_client, send_statsd, TASK_CONTAINER_NAME_TAG
from ecs_container_exporter.cpu_metrics import calculate_cpu_metrics
from ecs_container_exporter.memory_metrics import calculate_memory_metrics
from ecs_container_exporter.io_metrics import calculate_io_metrics
from ecs_container_exporter.network_metrics import calculate_network_metrics

import logging
log = logging.getLogger(__name__)


class ECSContainerExporter(object):

    include_containers = []
    exclude_containers = []
    # 1 - healthy, 0 - unhealthy
    exporter_status = 1
    # initial task metrics that do not change
    static_task_metrics = []
    # individual container tags
    task_container_tags = {}
    # task limits
    task_cpu_limit = 0
    task_mem_limit = 0
    # individual container limits
    task_container_limits = {}
    # the Task level metrics are included by default
    include_container_ids = [TASK_CONTAINER_NAME_TAG]

    def __init__(self, metadata_url=None, include_containers=None, exclude_containers=None, http_timeout=60):

        self.task_metadata_url = urljoin(metadata_url + '/', 'task')
        # For testing
        # self.task_stats_url = urljoin(metadata_url + '/', 'stats')
        self.task_stats_url = urljoin(metadata_url + '/', 'task/stats')

        if exclude_containers:
            self.exclude_containers = exclude_containers
        if include_containers:
            self.include_containers = include_containers

        self.http_timeout = http_timeout

        self.log = logging.getLogger(__name__)
        self.collect_static_metrics()

    def start_prometheus_eporter(self, exporter_port):
        self.log.info(f'Exporter initialized with '
                      f'metadata_url: {self.task_metadata_url}, '
                      f'task_stats_url: {self.task_stats_url}, '
                      f'http_timeout: {self.http_timeout}, '
                      f'include_containers: {self.include_containers}, '
                      f'exclude_containers: {self.exclude_containers}')

        REGISTRY.register(self)
        # Start exporter http service
        start_http_server(int(exporter_port))
        while True:
            time.sleep(10)

    def send_statsd_metrics(self, statsd_host, statsd_port):
        init_statsd_client(statsd_host, statsd_port)
        for metric in self.collect_all_metrics():
            send_statsd(metric)

    def collect_static_metrics(self):
        while True:
            # some wait for the task to be in running state
            time.sleep(5)
            try:
                response = requests.get(self.task_metadata_url, timeout=self.http_timeout)

            except requests.exceptions.Timeout:
                msg = f'Metadata url {self.task_metadata_url} timed out after {self.http_timeout} seconds'
                self.exporter_status = 0
                self.log.exception(msg)
                continue

            except requests.exceptions.RequestException:
                msg = f'Error fetching from Metadata url {self.task_metadata_url}'
                self.exporter_status = 0
                self.log.exception(msg)
                continue

            if response.status_code != 200:
                msg = f'Url {self.task_metadata_url} responded with {response.status_code} HTTP code'
                self.exporter_status = 0
                self.log.error(msg)
                continue

            try:
                metadata = response.json()

            except ValueError:
                msg = f'Cannot decode metadata url {self.task_metadata_url} response {response.text}'
                self.exporter_status = 0
                self.log.error(msg, exc_info=True)
                continue

            if metadata.get('KnownStatus') != 'RUNNING':
                self.log.warning(f'ECS Task not yet in RUNNING state, current status is: {metadata["KnownStatus"]}')
                continue
            else:
                break

        self.log.debug(f'Discovered Task metadata: {metadata}')
        self.parse_task_metadata(metadata)

    def parse_task_metadata(self, metadata):
        self.static_task_metrics = []
        self.task_container_tags = {}
        self.task_container_limits = {}

        # task cpu/mem limit
        task_tag = task_metric_tags()
        self.task_cpu_limit, self.task_mem_limit = self.cpu_mem_limit(metadata)

        metric = create_metric('cpu_limit', self.task_cpu_limit, task_tag, 'gauge', 'Task CPU limit')
        self.static_task_metrics.append(metric)

        metric = create_metric('mem_limit', self.task_mem_limit, task_tag, 'gauge', 'Task Memory limit')
        self.static_task_metrics.append(metric)

        # container tags and limits
        for container in metadata['Containers']:
            container_id = container['DockerId']
            container_name = container['Name']

            if self.should_process_container(container_name,
                                             self.include_containers,
                                             self.exclude_containers):
                self.log.info(f'Processing stats for container: {container_name} - {container_id}')
                self.include_container_ids.append(container_id)
            else:
                self.log.info(f'Excluding container: {container_name} - {container_id} as per exclusion')

            self.task_container_tags[container_id] = {'container_name': container_name}

            # container cpu/mem limit
            cpu_value, mem_value = self.cpu_mem_limit(container)
            self.task_container_limits[container_id] = {'cpu': cpu_value,
                                                        'mem': mem_value}

            if container_id in self.include_container_ids:
                metric = create_metric('cpu_limit', cpu_value, self.task_container_tags[container_id],
                                       'gauge', 'Limit in percent of the CPU usage')
                self.static_task_metrics.append(metric)

                metric = create_metric('mem_limit', mem_value, self.task_container_tags[container_id],
                                       'gauge', 'Limit in memory usage in MBs')
                self.static_task_metrics.append(metric)

    def should_process_container(self, container_name, include_containers, exclude_containers):
        if container_name in exclude_containers:
            return False
        else:
            if include_containers:
                if container_name in include_containers:
                    return True
                else:
                    return False
            else:
                return True

    def cpu_mem_limit(self, metadata):
        # normalise to `cpu shares`
        cpu_limit = metadata.get('Limits', {}).get('CPU', 0) * 1024
        mem_limit = metadata.get('Limits', {}).get('Memory', 0)

        return (
            cpu_limit, mem_limit
        )

    # All metrics are collected here
    def collect_all_metrics(self):
        container_metrics = self.collect_container_metrics()

        # exporter status metric
        metric = create_metric('exporter_status', self.exporter_status, {},
                               'gauge', 'Exporter Status')
        container_metrics.append(metric)

        return self.static_task_metrics + container_metrics

    # prometheus exporter collect function
    def collect(self):
        for metric in self.collect_all_metrics():
            yield create_prometheus_metric(metric)

    def collect_container_metrics(self):
        metrics = []

        try:
            request = requests.get(self.task_stats_url)

        except requests.exceptions.Timeout:
            msg = f'Task stats url {self.task_stats_url} timed out after {self.http_timeout} seconds'
            self.exporter_status = 0
            self.log.warning(msg)
            return metrics

        except requests.exceptions.RequestException:
            msg = f'Error fetching from task stats url {self.task_stats_url}'
            self.exporter_status = 0
            self.log.warning(msg)
            return metrics

        if request.status_code != 200:
            msg = f'Url {self.task_stats_url} responded with {request.status_code} HTTP code'
            self.exporter_status = 0
            self.log.error(msg)
            return metrics

        try:
            stats = request.json()
            self.exporter_status = 1

        except ValueError:
            msg = 'Cannot decode task stats {self.task_stats_url} url response {request.text}'
            self.exporter_status = 0
            self.log.warning(msg, exc_info=True)
            return metrics

        container_metrics_all = self.parse_container_metadata(stats,
                                                              self.task_cpu_limit,
                                                              self.task_container_limits,
                                                              self.task_container_tags)

        # flatten and filter excluded containers
        filtered_container_metrics = []
        for metrics_by_container in container_metrics_all:
            for container_id, metrics in metrics_by_container.items():
                if container_id in self.include_container_ids:
                    filtered_container_metrics.extend(metrics)

        return filtered_container_metrics

    def parse_container_metadata(self, stats, task_cpu_limit,
                                 task_container_limits, task_container_tags):
        """
        More details on the exposed docker metrics
        https://github.com/moby/moby/blob/c1d090fcc88fa3bc5b804aead91ec60e30207538/api/types/stats.go

        """
        container_metrics_all = []
        try:
            # CPU metrics
            container_metrics_all.append(
                calculate_cpu_metrics(stats,
                                      task_cpu_limit,
                                      task_container_limits,
                                      task_container_tags)
            )

            # Memory metrics
            container_metrics_all.append(
                calculate_memory_metrics(stats, task_container_tags)
            )

            # I/O metrics
            container_metrics_all.append(
                calculate_io_metrics(stats, task_container_tags)
            )

            # network metrics
            container_metrics_all.append(
                calculate_network_metrics(stats, task_container_tags)
            )

        except Exception as e:
            self.log.warning("Could not retrieve metrics for {}: {}".format(task_container_tags, e), exc_info=True)
            self.exporter_status = 1

        return container_metrics_all


def shutdown(sig_number, frame):
    log.info("Recevied signal {}, Shuttting down".format(sig_number))
    sys.exit(0)


@click.command()
@click.option('--metadata-url', envvar='ECS_CONTAINER_METADATA_URI', type=str, default=None,
              help='Override ECS Metadata Url')
@click.option('--exporter-port', envvar='EXPORTER_PORT', type=int, default=9545,
              help='Change exporter listen port')
@click.option('--use-statsd', envvar='USE_STATSD', is_flag=True, type=bool, default=False,
              help='Emit metrics to statsd instead of starting Prometheus exporter')
@click.option('--statsd-port', envvar='STATSD_PORT', type=int, default=None,
              help='Override Stasd Port')
@click.option('--statsd-host', envvar='STATSD_HOST', type=str, default='localhost',
              help='Override Stasd Host')
@click.option('--statsd-port', envvar='STATSD_PORT', type=int, default=8125,
              help='Override Stasd Port')
@click.option('--include', envvar='INCLUDE', type=str, default=None,
              help='Comma seperated list of container names to include, or use env var INCLUDE')
@click.option('--exclude', envvar='EXCLUDE', type=str, default=None,
              help='Comma seperated list of container names to exclude, or use env var EXCLUDE')
@click.option('--log-level', envvar='LOG_LEVEL', type=str, default='INFO',
              help='Log level, default: INFO')
def main(
    metadata_url=None, exporter_port=9545, use_statsd=False, statsd_port=8125, statsd_host='localhost',
    include=None, exclude=None, log_level='INFO'
):
    if not metadata_url:
        sys.exit('AWS environment variable ECS_CONTAINER_METADATA_URI not found '
                 'nor is --metadata-url set')

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    logging.basicConfig(
        format='%(asctime)s:%(levelname)s:%(message)s',
    )
    logging.getLogger().setLevel(
        getattr(logging, log_level.upper())
    )

    if exclude:
        exclude=exclude.strip().split(',')
    if include:
        include=include.strip().split(',')

    collector = ECSContainerExporter(metadata_url=metadata_url,
                                     include_containers=include,
                                     exclude_containers=exclude)

    if use_statsd:
        collector.send_statsd_metrics(statsd_host, statsd_port)
    else:
        collector.start_prometheus_eporter(exporter_port)


if __name__ == '__main__':
    main()
