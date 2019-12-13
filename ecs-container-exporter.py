#!/usr/bin/env python3
import os
import sys
import time
import click
import signal
import requests
from requests.compat import urljoin

from prometheus_client import start_http_server
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, REGISTRY

import logging
logging.basicConfig(
    format='%(asctime)s:%(levelname)s:%(message)s',
    level=logging.INFO
)

# Default value is maxed out for some cgroup metrics
CGROUP_NO_VALUE = 0x7FFFFFFFFFFFF000


class ECSContainerExporter(object):

    exclude_containers = []
    _prefix = 'ecs_container_'
    # 1 - healthy, 0 - unhealthy
    exporter_status = 1
    # task level container metrics
    task_container_metrics = []
    # individual container tags
    task_container_tags = {}

    def __init__(self, metadata_url=None, exclude_containers=None, http_timeout=60):

        self.task_metadata_url = urljoin(metadata_url + '/', 'task')
        self.task_stats_url = urljoin(metadata_url + '/', 'task/stats')

        if exclude_containers:
            self.exclude_containers = exclude_containers

        self.http_timeout = http_timeout

        self.log = logging.getLogger(__name__)
        self.log.info(f'Exporter initialized with '
                      f'metadata_url: {self.task_metadata_url}, '
                      f'task_stats_url: {self.task_stats_url}, '
                      f'http_timeout: {self.http_timeout}, '
                      f'exclude_containers: {self.exclude_containers}')

        self.discover_task_metadata()
        REGISTRY.register(self)

    def discover_task_metadata(self):
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

            metadata = {}
            try:
                metadata = response.json()
            except ValueError:
                msg = f'Cannot decode metadata url {self.task_metadata_url} response {response.text}'
                self.exporter_status = 0
                self.log.error(msg, exc_info=True)
                continue

            if metadata['KnownStatus'] != 'RUNNING':
                self.log.warning(f'ECS Task not yet in RUNNING state, current status is: {metadata["KnownStatus"]}')
                continue
            else:
                break

        self.log.debug(f'Discovered Task metadata: {metadata}')
        self.parse_task_metadata(metadata)

    def parse_task_metadata(self, metadata):
        self.task_container_metrics = []
        self.task_container_tags = {}

        for container in metadata['Containers']:
            container_id = container['DockerId']
            container_name = container['Name']
            if container_name in self.exclude_containers:
                self.log.info(f'Excluding container: {container_name} - {container_id} as per exclusion')
            else:
                self.task_container_tags[container_id] = {'container_name': container_name}
                self.log.info(f'Processing stats for container: {container_name} - {container_id}')

                # Cpu limit metric
                value = container.get('Limits', {}).get('CPU', 0)
                metric = self.create_metric('cpu_limit', value, self.task_container_tags[container_id],
                                            'gauge', 'Limit in percent of the CPU usage')
                self.task_container_metrics.append(metric)

    # every http request gets data from here
    def collect(self):
        container_metrics = self.discover_container_metadata()

        # exporter status metric
        metric = GaugeMetricFamily(self._prefix + 'exporter_status', 'exporter status')
        metric.add_metric(value=self.exporter_status, labels=())
        container_metrics.append(metric)

        return self.task_container_metrics + container_metrics

    def discover_container_metadata(self):
        try:
            request = requests.get(self.task_stats_url)

        except requests.exceptions.Timeout:
            msg = f'Task stats url {self.task_stats_url} timed out after {self.http_timeout} seconds'
            self.exporter_status = 0
            self.log.warning(msg)
            return []

        except requests.exceptions.RequestException:
            msg = f'Error fetching from task stats url {self.task_stats_url}'
            self.exporter_status = 0
            self.log.warning(msg)
            return []

        if request.status_code != 200:
            msg = f'Url {self.task_stats_url} responded with {request.status_code} HTTP code'
            self.exporter_status = 0
            self.log.error(msg)
            return []

        stats = {}
        try:
            stats = request.json()

        except ValueError:
            msg = 'Cannot decode task stats {self.task_stats_url} url response {request.text}'
            self.exporter_status = 0
            self.log.warning(msg, exc_info=True)
            return []

        container_metrics = []
        for container_id, container_stats in stats.items():
            if container_id in self.task_container_tags and container_stats:
                container_metrics.extend(
                    self.parse_container_metadata(container_stats, self.task_container_tags[container_id])
                )

        self.exporter_status = 1
        return container_metrics

    def create_metric(self, name, value, tags, type, desc=''):
        if type == 'counter':
            metric = CounterMetricFamily(self._prefix + name, desc, labels=tags.keys())
        elif type == 'gauge':
            metric = GaugeMetricFamily(self._prefix + name, desc, labels=tags.keys())
        else:
            raise Exception(f'Unknown metric type: {type}')

        metric.add_metric(labels=tags.values(), value=value)
        return metric

    def calculate_cpu_metrics(self, cpu_stats, prev_cpu_stats, tags):
        """
        Calculate cpu metrics based on the stats json:

        "cpu_stats": {
            "cpu_usage": {
                "percpu_usage": [
                    826860687,
                    830807540,
                    823365887,
                    844077056
                ],
                "total_usage": 3325111170,
                "usage_in_kernelmode": 1620000000,
                "usage_in_usermode": 1600000000
            },
            "online_cpus": 4,
            "system_cpu_usage": 35595977360000000,
            "throttling_data": {
                "periods": 0,
                "throttled_periods": 0,
                "throttled_time": 0
            }
        },

        """
        metrics = []

        # Calculate cpu usage as per `docker stats` command:
        # https://github.com/docker/cli/blob/6c12a82f330675d4e2cfff4f8b89a353bcb1fecd/cli/command/container/stats_helpers.go#L166
        #
        curr_usage = cpu_stats.get('cpu_usage', {}).get('total_usage')
        curr_system = cpu_stats.get('system_cpu_usage')
        prev_usage = prev_cpu_stats.get('cpu_usage', {}).get('total_usage')
        prev_system = prev_cpu_stats.get('system_cpu_usage')

        if prev_usage and prev_system:
            usage_delta = float(curr_usage) - float(prev_usage)
            system_delta = float(curr_system) - float(prev_system)

            cpu_percent = usage_delta / system_delta
        else:
            cpu_percent = 0.0

        metric = self.create_metric('cpu_usage_ratio', round(cpu_percent, 4), tags, 'gauge',
                                    'CPU usage ratio')
        metrics.append(metric)

        # per cpu metrics
        percpu_usage = cpu_stats.get('cpu_usage', {}).get('percpu_usage', [])
        prev_percpu_usage = prev_cpu_stats.get('cpu_usage', {}).get('percpu_usage', [])
        for i, value in enumerate(percpu_usage):
            # Skip inactive CPUs - https://github.com/torvalds/linux/commit/5ca3726
            if value != 0:
                cpu_tags = tags.copy()
                cpu_tags['cpu'] = str(i)
                if prev_percpu_usage[i]:
                    usage_delta = float(value) - float(prev_percpu_usage[i])
                    usage_percent = usage_delta / system_delta
                else:
                    usage_percent = 0.0
                metric = self.create_metric('percpu_usage_ratio', round(usage_percent, 4), cpu_tags, 'gauge',
                                            'Per CPU usage ratio')
                metrics.append(metric)

        # Misc cpu metrics
        value = cpu_stats.get('cpu_usage', {}).get('usage_in_kernelmode')
        metric = self.create_metric('cpu_kernelmode', value, tags, 'counter',
                                    'Same as system CPU usage reported in nanoseconds')
        metrics.append(metric)

        value = cpu_stats.get('cpu_usage', {}).get('usage_in_usermode')
        metric = self.create_metric('cpu_usermode', value, tags, 'counter',
                                    'Same as user CPU usage reported in nanoseconds')
        metrics.append(metric)

        # cpu throttling
        throttling_data = cpu_stats.get('throttling_data')
        for mkey, mvalue in throttling_data.items():
            metric = self.create_metric('throttle_' + mkey, value, tags, 'counter')
            metrics.append(metric)

        return metrics

    def parse_container_metadata(self, container_stats, task_container_tags):
        metrics = []
        try:
            # CPU metrics
            cpu_stats = container_stats.get('cpu_stats', {})
            prev_cpu_stats = container_stats.get('precpu_stats', {})

            metrics.extend(self.calculate_cpu_metrics(cpu_stats, prev_cpu_stats, task_container_tags))

            # Memory metrics
            memory_stats = container_stats.get('memory_stats', {})

            for mkey in ['cache']:
                value = memory_stats.get('stats', {}).get(mkey)
                # some values have default garbage value
                if value < CGROUP_NO_VALUE:
                    metric = self.create_metric('mem_' + mkey, value, task_container_tags, 'gauge')
                    metrics.append(metric)

            for mkey in ['max_usage', 'usage', 'limit']:
                value = memory_stats.get(mkey)
                # some values have default garbage value
                if value < CGROUP_NO_VALUE:
                    metric = self.create_metric('mem_' + mkey, value, task_container_tags, 'gauge')
                    metrics.append(metric)

            # TODO: I/O metrics

        except Exception as e:
            self.log.warning("Cold not retrieve metrics for {}: {}".format(task_container_tags, e), exc_info=True)

        return metrics


def shutdown(sig_number, frame):
    print("Recevied signal {}, Shuttting down".format(sig_number))
    sys.exit(0)


@click.command()
@click.option('--metadata-url', type=str, default=None, help='Override ECS Metadataurl')
@click.option('--exclude', type=str, default=None, help='Comma seperated list of container names to exclude')
def main(metadata_url=None, exclude=None):
    metadata_url = metadata_url or os.environ.get('ECS_CONTAINER_METADATA_URI', None)

    if not metadata_url:
        sys.exit('AWS environment variable ECS_CONTAINER_METADATA_URI not found '
                 'nor is --metadata-url set')

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    if exclude:
        exclude_containers=exclude.strip().split(',')
    ECSContainerExporter(metadata_url=metadata_url, exclude_containers=exclude_containers)
    # Start up the server to expose the metrics.
    start_http_server(9545)
    while True:
        time.sleep(10)


if __name__ == '__main__':
    main()
