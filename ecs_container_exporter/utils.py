import logging
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

# special container name tag for Task level (instead of container) metrics
TASK_CONTAINER_NAME_TAG = '_task_'
METRIC_PREFIX = 'ecs_task_'

logging.basicConfig(
    format='%(asctime)s:%(levelname)s:%(message)s',
)


def get_logger(log_level):
    return logging.getLogger()


def create_metric(name, *args):
    return publish_metric(METRIC_PREFIX + name, *args)


def publish_metric(name, value, tags, type, desc=''):
    if type == 'counter':
        metric = CounterMetricFamily(name, desc, labels=tags.keys())
    elif type == 'gauge':
        metric = GaugeMetricFamily(name, desc, labels=tags.keys())
    else:
        raise Exception(f'Unknown metric type: {type}')

    metric.add_metric(labels=tags.values(), value=value)
    return metric


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


def task_metric_tags():
    """
    Special tag that will apply to `task` level metrics, as opposed to
    `container` level metrics.

    """
    return {'container_name': TASK_CONTAINER_NAME_TAG}
