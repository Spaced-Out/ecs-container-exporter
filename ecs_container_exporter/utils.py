import requests
import logging
from collections import namedtuple
from datadog.dogstatsd.base import DogStatsd
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

# special container name tag for Task level (instead of container) metrics
TASK_CONTAINER_NAME_TAG = '_task_'
METRIC_PREFIX = 'ecs_task'

logging.basicConfig(
    format='%(asctime)s:%(levelname)s:%(message)s',
)

Metric = namedtuple('Metric', ['name', 'value', 'tags', 'type', 'desc'])

statsd = None


def init_statsd_client(statsd_host='localhost', statsd_port=8125):
    global statsd
    if not statsd:
        statsd = DogStatsd(
            statsd_host, statsd_port,
            use_ms=True,
            namespace=METRIC_PREFIX
        )


def get_logger(log_level):
    return logging.getLogger()


def create_metric(name, value, tags, type, desc=''):
    return Metric(name, value, tags, type, desc)


def create_prometheus_metric(metric):
    metric_name = METRIC_PREFIX +'_'+ metric.name
    if metric.type == 'counter':
        pm = CounterMetricFamily(metric_name, metric.desc, labels=metric.tags.keys())
    elif metric.type == 'gauge':
        pm = GaugeMetricFamily(metric_name, metric.desc, labels=metric.tags.keys())
    else:
        raise Exception(f'Unknown metric type: {metric.type}')

    pm.add_metric(labels=metric.tags.values(), value=metric.value)
    return pm


def format_dogstatsd_tags(tags):
    """
    {k: v} => ['k:v']

    """
    return [f'{k}:{v}' for k, v in tags.items()]


def send_statsd(metric):
    global statsd
    tags = format_dogstatsd_tags(metric.tags)
    if metric.type == 'counter':
        statsd.increment(metric.name, metric.value, tags=tags)
    elif metric.type == 'gauge':
        statsd.gauge(metric.name, metric.value, tags=tags)
    else:
        raise Exception(f'Unknown metric type: {metric.type}')


def create_task_metrics(task_metrics, metric_type):
    """
    Convert task_metrics key, value hash to actual metrics

    """
    metrics = []
    tags = task_metric_tags()
    for mkey, mvalue in task_metrics.items():
        metrics.append(
            create_metric(mkey, mvalue, tags, metric_type)
        )

    return metrics


def ecs_task_metdata(url, timeout):
    response = requests.get(url, timeout=timeout)

    if response.status_code != 200:
        raise Exception(f'Error: Non 200 response from url {url}')

    try:
        return response.json()

    except ValueError as e:
        raise Exception(f'Error: decoding json response from url {url} response {response.text}: {e}')


def task_metric_tags():
    """
    Special tag that will apply to `task` level metrics, as opposed to
    `container` level metrics.

    """
    return {'container_name': TASK_CONTAINER_NAME_TAG}
