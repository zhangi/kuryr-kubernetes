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

LOG = logging.getLogger(__name__)


class AnnotationPodSecurityGroupsDriver(base.PodSecurityGroupsDriver):
    """Provides security groups for Pod based on annotation."""

    def get_security_groups(self, pod, project_id):
        LOG.debug(
            "AnnotationPodSecurityGroupsDriver: pod: %s, annotations: %s",
            pod['metadata']['name'], pod['metadata']['annotations'])

        annotations = pod['metadata']['annotations']
        os_net = clients.get_network_client()
        sg = os_net.find_security_group(
            annotations[constants.K8S_ANNOTATION_SECGROUP])
        sg_id_list = []
        if sg:
            sg_id_list.append(sg.id)
        LOG.debug("AnnotationPodSecurityGroupsDriver: sg_list: %s", sg_id_list)
        return sg_id_list

    def create_sg_rules(self, pod):
        LOG.debug("Security group driver does not create SG rules for "
                  "the pods.")

    def delete_sg_rules(self, pod):
        LOG.debug("Security group driver does not delete SG rules for "
                  "the pods.")

    def update_sg_rules(self, pod):
        LOG.debug("Security group driver does not update SG rules for "
                  "the pods.")

    def delete_namespace_sg_rules(self, namespace):
        LOG.debug("Security group driver does not delete SG rules for "
                  "namespace.")

    def create_namespace_sg_rules(self, namespace):
        LOG.debug("Security group driver does not create SG rules for "
                  "namespace.")

    def update_namespace_sg_rules(self, namespace):
        LOG.debug("Security group driver does not update SG rules for "
                  "namespace.")


class AnnotationServiceSecurityGroupsDriver(base.ServiceSecurityGroupsDriver):
    """Provides security groups for Service based on annotation."""

    def get_security_groups(self, service, project_id):
        LOG.debug(
            "AnnotationServiceSecurityGroupsDriver: svc: %s, annotations: %s",
            service['metadata']['name'], service['metadata']['annotations'])

        annotations = service['metadata']['annotations']
        os_net = clients.get_network_client()
        sg = os_net.find_security_group(
            annotations[constants.K8S_ANNOTATION_SECGROUP])

        sg_id_list = []
        if sg:
            sg_id_list.append(sg.id)
        LOG.debug("AnnotationServiceSecurityGroupsDriver: sg: %s",
                  sg)
        return sg_id_list
