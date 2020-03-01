import collections
import contextlib
import libvirt
import logging
import re

from lxml import etree

from prometheus_client.core import (
    GaugeMetricFamily,
    InfoMetricFamily,
)

LOG = logging.getLogger(__name__)
re_invalid_chars = re.compile(r'[^\w]+')


def makemetricname(name):
    name = re_invalid_chars.sub('_', name)
    return 'libvirt_{}'.format(name)


class BundledMetrics(object):
    def __init__(self):
        self.metrics = collections.defaultdict(
            lambda: collections.defaultdict(
                dict))

    def add(self, ns, index, subkey, val):
        name = '.'.join([ns] + subkey)
        self.metrics[ns][index][name] = val

    def generate_metrics(self, uuid):
        for ns, metrics in self.metrics.items():
            name_attr = '{}.name'.format(ns)
            for i, metric in metrics.items():
                labels = {
                    'uuid': uuid,
                    'unit': str(i),
                }

                if name_attr in metric:
                    labels['name'] = metric[name_attr]

                yield InfoMetricFamily(
                    'libvirt_{}'.format(ns),
                    'information about {ns} {unit}'.format(
                        ns=ns,
                        unit=labels['unit'],
                    ),
                    value=labels
                )

                for name, val in metric.items():
                    if name == name_attr:
                        continue

                    if not isinstance(val, (float, int)):
                        LOG.debug('dom %s ns %s unit %s: '
                                  'skipping non-numeric metric %s',
                                  uuid, ns, i, name)
                        continue

                    m = GaugeMetricFamily(
                        makemetricname(name),
                        'libvirt {}'.format(name),
                        labels=['uuid', 'unit']
                    )

                    m.add_metric([uuid, str(i)], val)

                    yield m


class LibvirtCollector(object):
    def __init__(self, uri=None, dom_label_map=None):
        self.uri = uri
        self.dom_label_map = dom_label_map

    @contextlib.contextmanager
    def connection(self):
        LOG.info('connecting to libvirt at uri %s',
                 self.uri if self.uri else '<default>')
        conn = libvirt.open(self.uri)
        yield conn
        LOG.info('closing libvirt connection')
        conn.close()

    def describe(self):
        return []

    def add_domain_labels(self, dom):
        doc = etree.fromstring(dom.XMLDesc())
        labels = {}
        for name, path in self.dom_label_map['labels'].items():
            val = doc.xpath(path,
                            namespaces=self.dom_label_map.get(
                                'namespaces', {}))
            if len(val) > 0:
                labels[name] = val[0]

        return labels

    def collect(self):
        LOG.info('collecting metrics')
        with self.connection() as conn:
            all_dom_stats = conn.getAllDomainStats(
                0, libvirt.VIR_CONNECT_GET_ALL_DOMAINS_STATS_ACTIVE)
            LOG.debug('found stats for %d domains', len(all_dom_stats))

            for dom, stats in all_dom_stats:
                uuid = dom.UUIDString()
                name = dom.name()
                LOG.debug('collecting metrics for dom %s name %s', uuid, name)

                domlabels = {
                    'uuid': uuid,
                    'name': name,
                }

                if self.dom_label_map:
                    domlabels.update(self.add_domain_labels(dom))

                yield InfoMetricFamily(
                    'libvirt_active',
                    'information about libvirt domain',
                    value=domlabels,
                )

                bundle = BundledMetrics()
                for name, val in stats.items():
                    comps = name.split('.')
                    if comps[1].isdigit():
                        subkey = comps[2:]
                        bundle.add(comps[0], comps[1], subkey, val)
                        continue

                    m = GaugeMetricFamily(
                        makemetricname(name),
                        'libvirt {}'.format(name),
                        labels=['uuid'],
                    )

                    m.add_metric([uuid], val)

                    yield m

                yield from bundle.generate_metrics(uuid)
