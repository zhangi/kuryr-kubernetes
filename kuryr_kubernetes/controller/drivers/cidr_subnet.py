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

from kuryr_kubernetes import config
from kuryr_kubernetes.controller.drivers import base
from kuryr_kubernetes import exceptions
from kuryr_kubernetes import utils

LOG = logging.getLogger(__name__)


class CIDRPodSubnetDriver(base.PodSubnetsDriver):
    """Provides subnet for Pod port based on pod_net_cidr option."""

    def get_subnets(self, pod, project_id):
        LOG.debug("CIDRPodSubnetDriver: pod: %s, project_id: %s",
                  pod['metadata']['name'], project_id)

        subnet_id = utils.get_subnet_id(
            project_id=project_id,
            cidr=config.CONF.neutron_defaults.pod_net_cidr)

        if not subnet_id:
            raise exceptions.ResourceNotReady(
                "subnet of project %s" % (project_id,))
        LOG.debug("CIDRPodSubnetDriver: subnet_id: %s",
                  subnet_id)
        return {subnet_id: utils.get_subnet(subnet_id)}


class CIDRServiceSubnetDriver(base.ServiceSubnetsDriver):
    """Provides subnet for Service's LBaaS based on svc_net_cidr option."""

    def get_subnets(self, service, project_id):
        LOG.debug("CIDRServiceSubnetDriver: svc: %s, project_id: %s",
                  service['metadata']['name'], project_id)

        subnet_id = utils.get_subnet_id(
            project_id=project_id,
            cidr=config.CONF.neutron_defaults.svc_net_cidr)

        if not subnet_id:
            raise exceptions.ResourceNotReady(
                "subnet of project %s" % (project_id,))
        LOG.debug("CIDRServiceSubnetDriver: subnet_id: %s",
                  subnet_id)
        return {subnet_id: utils.get_subnet(subnet_id)}
