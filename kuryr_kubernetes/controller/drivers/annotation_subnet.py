# Copyright (c) 2016 Mirantis, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base
from kuryr_kubernetes import exceptions
from kuryr_kubernetes import utils

LOG = logging.getLogger(__name__)


class AnnotationPodSubnetDriver(base.PodSubnetsDriver):
    """Provides subnet for Pod port based on annotation."""

    def get_subnets(self, pod, project_id):
        LOG.debug("AnnotationPodSubnetDriver: pod: %s, annotations: %s",
                  pod['metadata']['name'], pod['metadata'].get('annotations'))
        subnet_id = config.CONF.neutron_defaults.pod_subnet
        try:
            annotations = pod['metadata']['annotations']
            subnet_id = annotations[constants.K8S_ANNOTATION_SUBNET]
        except KeyError:
            return {subnet_id: utils.get_subnet(subnet_id)}

        os_net = clients.get_network_client()
        subnet = os_net.find_network(subnet_id)
        if not subnet:
            raise exceptions.ResourceNotReady(
                "subnet: %s" % (subnet_id,))
        LOG.debug("AnnotationPodSubnetDriver: subnet_id: %s",
                  subnet.id)
        return {subnet.id: utils.get_subnet(subnet.id)}


class AnnotationServiceSubnetDriver(base.ServiceSubnetsDriver):
    """Provides subnet for Service's LBaaS based on annotation."""

    def get_subnets(self, service, project_id):
        LOG.debug("AnnotationServiceSubnetDriver: svc: %s, annotation: %s",
                  service['metadata']['name'],
                  service['metadata'].get('annotation'))

        subnet_id = config.CONF.neutron_defaults.service_subnet
        try:
            annotations = service['metadata']['annotations']
            subnet_id = annotations[constants.K8S_ANNOTATION_SUBNET]
        except KeyError:
            return {subnet_id: utils.get_subnet(subnet_id)}

        os_net = clients.get_network_client()
        subnet = os_net.find_network(subnet_id)

        if not subnet:
            raise exceptions.ResourceNotReady(
                "subnet: %s" % (subnet_id,))
        LOG.debug("AnnotationServiceSubnetDriver: subnet_id: %s",
                  subnet.id)
        return {subnet.id: utils.get_subnet(subnet.id)}
