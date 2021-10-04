
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


LOG = logging.getLogger(__name__)


class AnnotationPodProjectDriver(base.PodProjectDriver):
    """Provides project ID for Pod port based on annotation."""

    def get_project(self, pod):
        LOG.debug("AnnotationPodProjectDriver: pod %s",
                  pod['metadata']['name'])
        project_id = config.CONF.neutron_defaults.project

        try:
            annotations = pod['metadata']['annotations']
            subnet_id = annotations[constants.K8S_ANNOTATION_SUBNET]
        except KeyError:
            LOG.debug(
                "AnnotationPodProjectDriver: use default project_id %s",
                project_id)
            return project_id

        os_net = clients.get_network_client()
        subnet = os_net.get_subnet(subnet_id)
        project_id = subnet.project_id
        LOG.debug("AnnotationPodProjectDriver: project_id %s", project_id)

        return project_id


class AnnotationServiceProjectDriver(base.ServiceProjectDriver):
    """Provides project ID for Service based on annotation."""

    def get_project(self, service):
        project_id = config.CONF.neutron_defaults.project

        try:
            annotations = service['metadata']['annotations']
            subnet_id = annotations[constants.K8S_ANNOTATION_SUBNET]
        except KeyError:
            LOG.debug(
                "AnnotationServiceProjectDriver: use default project_id %s",
                project_id)
            return project_id

        os_net = clients.get_network_client()
        subnet = os_net.get_subnet(subnet_id)
        project_id = subnet.project_id
        LOG.debug("AnnotationServiceProjectDriver: project_id %s", project_id)
        return project_id
