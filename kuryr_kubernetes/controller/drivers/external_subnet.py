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

from kuryr_kubernetes import exceptions
from kuryr_kubernetes.controller.drivers import base
from kuryr_kubernetes import utils

LOG = logging.getLogger(__name__)


class ExternalPodSubnetDriver(base.PodSubnetsDriver):
    """Provides subnet for Pod port based on an external API."""

    def get_subnets(self, pod, project_id):
        LOG.debug("ExternalPodSubnetDriver: pod: %s, project_id: %s",
                  pod['metadata']['name'], project_id)

        subnet_id = utils.get_subnet_id(
            project_id=project_id, cidr="11.1.0.0/16")

        if not subnet_id:
            raise exceptions.ResourceNotReady(
                "subnet of project %s" % (project_id,))
        LOG.debug("ExternalPodSubnetDriver: subnet_id: %s",
                  subnet_id)
        return {subnet_id: utils.get_subnet(subnet_id)}
