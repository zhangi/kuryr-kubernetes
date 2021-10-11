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
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import base
from kuryr_kubernetes import exceptions
from kuryr_kubernetes import utils

LOG = logging.getLogger(__name__)


class AnnotationPodSubnetDriver(base.PodSubnetsDriver):
    """Provides subnet for Pod port based on annotation."""

    def get_subnets(self, pod, project_id):
        LOG.debug("AnnotationPodSubnetDriver: pod: %s, annotations: %s",
                  pod['metadata']['name'], pod['metadata']['annotations'])

        annotations = pod['metadata']['annotations']
        os_net = clients.get_network_client()
        subnet = os_net.find_network(
            annotations[constants.K8S_ANNOTATION_SUBNET])

        if not subnet:
            raise exceptions.ResourceNotReady(
                "subnet of project %s" % (project_id,))
        LOG.debug("AnnotationPodSubnetDriver: subnet_id: %s",
                  subnet.id)
        return {subnet.id: utils.get_subnet(subnet.id)}


class AnnotationServiceSubnetDriver(base.ServiceSubnetsDriver):
    """Provides subnet for Service's LBaaS based on annotation."""

    def get_subnets(self, service, project_id):
        LOG.debug("AnnotationServiceSubnetDriver: svc: %s, project_id: %s",
                  service['metadata']['name'], project_id)

        annotations = service['metadata']['annotations']
        os_net = clients.get_network_client()
        subnet = os_net.find_network(
            annotations[constants.K8S_ANNOTATION_SUBNET])

        if not subnet.id:
            raise exceptions.ResourceNotReady(
                "subnet of project %s" % (project_id,))
        LOG.debug("AnnotationServiceSubnetDriver: subnet_id: %s",
                  subnet.id)
        return {subnet.id: utils.get_subnet(subnet.id)}
