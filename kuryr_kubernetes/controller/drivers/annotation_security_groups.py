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
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.controller.drivers import base

LOG = logging.getLogger(__name__)


class AnnotationPodSecurityGroupsDriver(base.PodSecurityGroupsDriver):
    """Provides security groups for Pod based on annotation."""

    def get_security_groups(self, pod, project_id) -> [str]:
        LOG.debug(
            "AnnotationPodSecurityGroupsDriver: pod: %s, annotations: %s",
            pod['metadata']['name'], pod['metadata'].get('annotations'))

        tenant_sg_ids = None
        if (ksg_name := pod['metadata']
                .get('annotations', {})
                .get(constants.K8S_ANNOTATION_SECGROUP_CRD, '')):
            k8s = clients.get_kubernetes_client()
            try:
                ksg = k8s.get_crd(
                    "kuryrsecuritygroups",
                    namespace=pod['metadata']['namespace'],
                    name=ksg_name,
                )
                tenant_sg_ids = ksg.get("status", {}).get(
                        "securityGroupIDs", [])
            except k_exc.K8sResourceNotFound:
                pass

        os_net = clients.get_network_client()
        if tenant_sg_ids is None:
            try:
                annotations = pod['metadata']['annotations']
                tenant_sg_ids = annotations[
                        constants.K8S_ANNOTATION_SECGROUP].split(',')
            except KeyError:
                pass

        if tenant_sg_ids is None:
            return list(config.CONF.neutron_defaults.pod_security_groups)

        sg_id_list = []
        for sg_id in tenant_sg_ids:
            sg = os_net.find_security_group(sg_id)
            if sg and sg.project_id == project_id:
                sg_id_list.append(sg.id)
        LOG.debug("AnnotationPodSecurityGroupsDriver: sg_id_list: %s",
                  sg_id_list)
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

    def get_security_groups(self, service, project_id) -> [str]:
        LOG.debug(
            "AnnotationServiceSecurityGroupsDriver: "
            "svc: %s, "
            "annotations: %s",
            service['metadata']['name'],
            service['metadata'].get('annotations'))

        tenant_sg_ids = None
        try:
            k8s = clients.get_kubernetes_client()
            ksg = k8s.get_crd(
                "kuryrsecuritygroups",
                namespace=service['metadata']['namespace'],
                name=service['metadata']['name'],
            )
            tenant_sg_ids = ksg.get("status", {}).get("securityGroupIDs", [])
        except k_exc.K8sResourceNotFound:
            pass

        if tenant_sg_ids is None:
            try:
                annotations = service['metadata']['annotations']
                tenant_sg_ids = annotations[
                        constants.K8S_ANNOTATION_SECGROUP].split(',')
            except KeyError:
                pass

        if tenant_sg_ids is None:
            return list(config.CONF.neutron_defaults.pod_security_groups)

        sg_id_list = []
        os_net = clients.get_network_client()
        for sg_id in tenant_sg_ids:
            sg = os_net.find_security_group(sg_id)
            if sg:
                sg_id_list.append(sg.id)
        LOG.debug("AnnotationServiceSecurityGroupsDriver: sg_id_list: %s",
                  sg_id_list)
        return sg_id_list
