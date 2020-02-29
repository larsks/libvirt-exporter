from __future__ import print_function

import click
import libvirt

from lxml import etree

nsmap = {
    'nova': 'http://openstack.org/xmlns/libvirt/nova/1.0',
    'libosinfo': 'http://libosinfo.org/xmlns/libvirt/domain/1.0',
}
xml_label_map = {
    'nova_user_name': '/domain/metadata/nova:instance/nova:owner/nova:user/text()',
    'nova_user_uuid': '/domain/metadata/nova:instance/nova:owner/nova:user/@uuid',
    'nova_project_name': '/domain/metadata/nova:instance/nova:owner/nova:project/text()',
    'nova_project_uuid': '/domain/metadata/nova:instance/nova:owner/nova:project/@uuid',
    'nova_flavor': '/domain/metadata/nova:instance/nova:flavor/@name',
}


def domxml_to_labels(dom):
    labels = {}
    doc = etree.fromstring(dom.XMLDesc())
    for label, path in xml_label_map.items():
        v = doc.xpath(path, namespaces=nsmap)
        if v:
            labels[label] = v[0]
    return labels


def bundle_to_metrics(bundle):
    metrics = []
    labels = {'index': bundle[1]}

    if 'name' in bundle[2]:
        labels['name'] = bundle[2]['name']

    for name, value in bundle[2].items():
        if name == 'name':
            continue

        k = '{}_{}'.format(bundle[0], name)
        metrics.append((k, labels, value))
    return metrics


def domstats_to_metrics(stats):
    newstats = []
    cur_bundle = (None, None, None)

    for k, v in stats.items():
        comps = k.split('.')
        if comps[1].isdigit():
            ns = comps[0]
            index = comps[1]
            if cur_bundle[:2] != (ns, index):
                if cur_bundle[0] is not None:
                    newstats.extend(bundle_to_metrics(cur_bundle))
                cur_bundle = (ns, index, {})

            k = '_'.join(comps[2:]).replace('-', '_')
            cur_bundle[2][k] = v
        else:
            k = k.replace('.', '_').replace('-', '_')
            newstats.append((k, {}, v))

    if cur_bundle[0] is not None:
        newstats.extend(bundle_to_metrics(cur_bundle))

    return newstats


@click.command()
@click.option('-c', '--connect', 'libvirt_uri')
@click.option('-l', '--label', 'labels', multiple=True, default=[])
def main(libvirt_uri, labels):
    host_labels = {}
    for label in labels:
        host_labels.update(dict([label.split('=')]))

    c = libvirt.open(libvirt_uri)
    all_stats = c.getAllDomainStats()
    active_stats = [x for x in all_stats if x[0].isActive()]

    for dom, stats in active_stats:
        metrics = domstats_to_metrics(stats)

        dom_labels = dict(
            domain=dom.name(),
            uuid=dom.UUIDString()
        )

        dom_labels.update(domxml_to_labels(dom))
        metrics.append(('active', dom_labels, 1))

        for metric in metrics:
            labels = metric[1]
            label_string = ','.join('{}="{}"'.format(k, v)
                                    for k, v in labels.items())
            print('libvirt_{} {{{}}} {}'.format(
                metric[0], label_string, metric[2]))


if __name__ == '__main__':
    main()
