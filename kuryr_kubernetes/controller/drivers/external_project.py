
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

from kuryr_kubernetes.controller.drivers import base


LOG = logging.getLogger(__name__)


class ExternalPodProjectDriver(base.PodProjectDriver):
    """Provides project ID for Pod port based on an external API."""

    def get_project(self, pod):
        LOG.debug("ExternalPodProjectDriver: pod %s", pod['metadata']['name'])

        name = pod['metadata']['name']
        project_id = name.split("-")[0]
        LOG.debug("ExternalPodProjectDriver: project_id %s", project_id)

        return project_id
