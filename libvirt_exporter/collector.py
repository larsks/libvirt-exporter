import contextlib
import json
import libvirt
import logging
import pkg_resources
import re

from lxml import etree
from prometheus_client.core import GaugeMetricFamily

LOG = logging.getLogger(__name__)

re_invalid_chars = re.compile(r'[^\w]+')


def makemetricname(name):
    name = re_invalid_chars.sub('_', name)
    return 'libvirt_{}'.format(name)


class Tree(dict):
    def __missing__(self, key):
        value = self[key] = type(self)()
        return value


class LibvirtCollector(object):
    def __init__(self, uri=None, xml_label_map=None):
        self.uri = uri
        self.xml_label_map = xml_label_map
        self.read_metric_descriptions()

    def read_metric_descriptions(self):
        self.description = {}
        s = pkg_resources.resource_stream(
            'libvirt_exporter', 'data/metrics.json')
        with contextlib.closing(s):
            descriptions = json.load(s)
            for desc in descriptions:
                self.description['libvirt_{}'.format(desc['name'])] = (
                    desc['desc']
                )
        LOG.debug('found %d metric descriptions',
                  len(self.description))

    @contextlib.contextmanager
    def connection(self):
        LOG.info('connecting to libvirt @ %s',
                 self.uri if self.uri else '<default>')
        self.conn = libvirt.open(self.uri)
        yield self.conn
        LOG.info('closing connection to libvirt')
        self.conn.close()

    def get_labels_from_xml(self, dom):
        dom_uuid = dom.UUIDString()
        doc = etree.fromstring(dom.XMLDesc())
        labels = {}
        for name, path in self.xml_label_map['labels'].items():
            LOG.debug('evaluating path %s for domain %s',
                      path, dom_uuid)
            val = doc.xpath(path,
                            namespaces=self.xml_label_map.get(
                                'namespaces', {}))
            if len(val) > 0:
                LOG.debug('adding label %s = %s to %s',
                          name, val[0], dom_uuid)
                labels[name] = val[0]

        return labels

    def collect(self):
        gauges = {}

        labelnames = ['dom_uuid', 'dom_name']
        if self.xml_label_map:
            labelnames.extend(self.xml_label_map['labels'].keys())

        up = GaugeMetricFamily('libvirt_domain_up',
                               'Metadata about a libvirt domain',
                               labels=labelnames)

        with self.connection():
            domstats = self.read_all_domstats()
            for dom, metrics in domstats.items():
                dom_uuid = dom.UUIDString()

                labels = {
                    'dom_uuid': dom_uuid,
                    'dom_name': dom.name(),
                }

                if self.xml_label_map:
                    labels.update(self.get_labels_from_xml(dom))

                LOG.debug('labels for %s: %s',
                          dom_uuid, labels)
                up.add_metric(
                    [labels.get(x, '') for x in labelnames],
                    1.0
                )

                flat = self.flatten(metrics,
                                    domlabels=dict(dom_uuid=dom_uuid))

                for name, labels, value in flat:
                    desc = self.description.get(
                        name, 'No documentation for {}'.format(name))
                    labelnames = labels.keys()
                    m = gauges.setdefault(
                        name, GaugeMetricFamily(name, desc,
                                                labels=labelnames))

                    m.add_metric(
                        labels.values(), value)

        yield up
        yield from iter(gauges.values())

    def read_all_domstats(self):
        metrics = Tree()
        for dom, stats in self.conn.getAllDomainStats(
                0, libvirt.VIR_CONNECT_GET_ALL_DOMAINS_STATS_ACTIVE):
            for name, val in stats.items():
                if not isinstance(val, (int, float)):
                    continue

                comps = name.split('.')
                cur = metrics[dom]
                last = None
                for comp in comps:
                    if last:
                        cur = cur[last]
                    last = comp

                cur[last] = val

        return metrics

    def flatten(self, cur, prefix=None, unit=None, domlabels=None, **labels):
        if prefix is None:
            prefix = []
        if unit is None:
            unit = []

        top = []

        if isinstance(cur, dict):
            for k, v in cur.items():
                if k == 'name':
                    top.extend(
                        self.flatten(1.0, prefix=prefix + ['info'], unit=unit,
                                     domlabels=domlabels, name=v, **labels)
                    )
                elif k.isdigit():
                    top.extend(
                        self.flatten(cur[k], prefix=prefix, unit=unit + [k],
                                     domlabels=domlabels, **labels)
                    )
                else:
                    top.extend(
                        self.flatten(cur[k], prefix=prefix + [k], unit=unit,
                                     domlabels=domlabels, **labels)
                    )

            return top
        else:
            if domlabels:
                labels.update(domlabels)
            if unit:
                labels['unit'] = '.'.join(unit)

            return [(makemetricname('_'.join(prefix)), labels, cur)]


if __name__ == '__main__':
    lv = LibvirtCollector()
    res = lv.collect()
