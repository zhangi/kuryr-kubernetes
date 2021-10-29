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

from kuryr.lib._i18n import _
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes import constants as k_const
from kuryr_kubernetes.controller.drivers import base as drv_base
from kuryr_kubernetes.controller.drivers import utils as driver_utils
from kuryr_kubernetes import exceptions as k_exc
from kuryr_kubernetes.handlers import k8s_base
from kuryr_kubernetes import utils

LOG = logging.getLogger(__name__)

SUPPORTED_SERVICE_TYPES = ('ClusterIP', 'LoadBalancer')


class ServiceHandler(k8s_base.ResourceEventHandler):
    """ServiceHandler handles K8s Service events.

    ServiceHandler handles K8s Service events and updates related Endpoints
    with LBaaSServiceSpec when necessary.
    """

    OBJECT_KIND = k_const.K8S_OBJ_SERVICE
    OBJECT_WATCH_PATH = "%s/%s" % (k_const.K8S_API_BASE, "services")

    def __init__(self):
        super(ServiceHandler, self).__init__()
        self._drv_project = drv_base.ServiceProjectDriver.get_instance()
        self._drv_subnets = drv_base.ServiceSubnetsDriver.get_instance()
        self._drv_sg = drv_base.ServiceSecurityGroupsDriver.get_instance()

    def _bump_network_policies(self, svc):
        if driver_utils.is_network_policy_enabled():
            driver_utils.bump_networkpolicies(svc['metadata']['namespace'])

    def on_present(self, service, *args, **kwargs):
        reason = self._should_ignore(service)
        if reason:
            LOG.debug(reason, service['metadata']['name'])
            return

        k8s = clients.get_kubernetes_client()
        loadbalancer_crd = k8s.get_loadbalancer_crd(service)
        try:
            if not self._patch_service_finalizer(service):
                return
        except k_exc.K8sClientException as ex:
            LOG.exception("Failed to set service finalizer: %s", ex)
            raise

        self._provision_x_service(service)

        if loadbalancer_crd is None:
            try:
                # Bump all the NPs in the namespace to force SG rules
                # recalculation.
                self._bump_network_policies(service)
                self.create_crd_spec(service)
            except k_exc.K8sNamespaceTerminating:
                LOG.warning('Namespace %s is being terminated, ignoring '
                            'Service %s in that namespace.',
                            service['metadata']['namespace'],
                            service['metadata']['name'])
                return
        elif self._has_lbaas_spec_changes(service, loadbalancer_crd):
            self._update_crd_spec(loadbalancer_crd, service)

    def _provision_x_service(self, service):
        x_service = self._build_x_service(service)
        if not x_service:
            return

        k8s = clients.get_kubernetes_client()
        try:
            k8s.add_finalizer(service, k_const.SERVICE_X_FINALIZER)
        except k_exc.K8sClientException as ex:
            LOG.exception("Failed to set x service finalizer: %s", ex)
            raise

        try:
            k8s.get(utils.get_res_link(x_service))
        except k_exc.K8sResourceNotFound:
            LOG.debug('Service %s not found.', x_service['metadata']['name'])
            endpoints = k8s.get(utils.get_endpoints_link(service))
            EndpointsHandler().on_present(endpoints)
            self._create_x_service(x_service)
            LOG.debug('Created service: %s', x_service['metadata']['name'])
            return
        except k_exc.K8sClientException:
            LOG.exception('Error retrieving ervice %s/%s.',
                          x_service['metadata']['namespace'],
                          x_service['metadata']['name'])
            raise

        try:
            k8s.patch('spec', utils.get_res_link(
                x_service), x_service['spec'])
        except k_exc.K8sResourceNotFound:
            LOG.debug('Service %s not found', x_service['metadata']['name'])
            raise
        except k_exc.K8sConflict:
            raise k_exc.ResourceNotReady(x_service)
        except k_exc.K8sClientException:
            LOG.exception('Error updating service %s',
                          x_service)

    def _build_x_service(self, service):
        annotations = service['metadata'].get('annotations', {})
        svc_name = service['metadata']['name']
        x_svc_name = annotations.get(k_const.K8S_ANNOTATION_X_SVC_NAME)
        x_svc_ip = annotations.get(k_const.K8S_ANNOTATION_X_SVC_IP)
        x_subnet_id = annotations.get(k_const.K8S_ANNOTATION_X_SUBNET)
        if not x_svc_name:
            return
        if not x_svc_ip:
            return
        if not x_subnet_id:
            return
        ports = []
        for port in service['spec']['ports']:
            ports.append({
                'targetPort': int(port['targetPort']),
                'port': port['port'],
                'protocol': port['protocol'],
            })

        return {
            'apiVersion': 'v1',
            'kind': 'Service',
            'metadata': {
                'namespace': service['metadata']['namespace'],
                'name': x_svc_name,
                'annotations': {
                    k_const.K8S_ANNOTATION_SVC_IP: x_svc_ip,
                    k_const.K8S_ANNOTATION_SUBNET: x_subnet_id,
                    k_const.K8S_ANNOTATION_SVC_NAME: svc_name,
                },
            },
            'spec': {
                'ports': ports,
            },
        }

    def _create_x_service(self, service):
        k8s = clients.get_kubernetes_client()
        try:
            k8s.post('{}/{}/services'.format(
                k_const.K8S_API_NAMESPACES,
                service['metadata']['namespace']),
                service)
        except k_exc.K8sConflict:
            raise k_exc.ResourceNotReady(service['metadata']['name'])
        except k_exc.K8sNamespaceTerminating:
            raise
        except k_exc.K8sClientException:
            LOG.exception("Exception when creating service %s.",
                          service['metadata']['name'])
            raise

    def _is_supported_type(self, service):
        spec = service['spec']
        return spec.get('type') in SUPPORTED_SERVICE_TYPES

    def _has_spec_annotation(self, service):
        return (k_const.K8S_ANNOTATION_LBAAS_SPEC in
                service['metadata'].get('annotations', {}))

    def _get_service_ip(self, service):
        annotations = service['metadata'].get('annotations', {})
        svc_ip = annotations.get(k_const.K8S_ANNOTATION_SVC_IP)
        if svc_ip:
            return svc_ip
        if self._is_supported_type(service):
            return service['spec'].get('clusterIP')
        return None

    def _should_ignore(self, service):
        if not self._has_clusterip(service):
            return 'Skipping headless Service %s.'
        if not self._is_supported_type(service):
            return 'Skipping service %s of unsupported type.'
        if self._has_spec_annotation(service):
            return ('Skipping annotated service %s, waiting for it to be '
                    'converted to KuryrLoadBalancer object and annotation '
                    'removed.')
        if utils.is_kubernetes_default_resource(service):
            # Avoid to handle default Kubernetes service as requires https.
            return 'Skipping default service %s.'
        return None

    def _patch_service_finalizer(self, service):
        k8s = clients.get_kubernetes_client()
        return k8s.add_finalizer(service, k_const.SERVICE_FINALIZER)

    def on_finalize(self, service, *args, **kwargs):
        k8s = clients.get_kubernetes_client()

        klb_crd_path = utils.get_klb_crd_path(service)
        # Bump all the NPs in the namespace to force SG rules
        # recalculation.
        self._bump_network_policies(service)
        try:
            k8s.delete(klb_crd_path)
        except k_exc.K8sResourceNotFound:
            k8s.remove_finalizer(service, k_const.SERVICE_FINALIZER)

        annotations = service['metadata'].get('annotations', {})
        x_svc_name = annotations.get(k_const.K8S_ANNOTATION_X_SVC_NAME)
        svc_name = annotations.get(k_const.K8S_ANNOTATION_SVC_NAME)
        namespace = service['metadata']['namespace']
        if x_svc_name:
            try:
                k8s.delete(f"{k_const.K8S_API_NAMESPACES}"
                           f"/{namespace}/services/{x_svc_name}")
            except k_exc.K8sResourceNotFound:
                k8s.remove_finalizer(
                    service, k_const.SERVICE_X_FINALIZER)
        elif svc_name:
            k8s.remove_finalizer(
                service, k_const.SERVICE_X_FINALIZER)

    def _has_clusterip(self, service):
        # ignore headless service, clusterIP is None
        return service['spec'].get('clusterIP') != 'None'

    def _get_subnet_id(self, service, project_id, ip):
        subnets_mapping = self._drv_subnets.get_subnets(service, project_id)
        subnet_ids = {
            subnet_id
            for subnet_id, network in subnets_mapping.items()
            for subnet in network.subnets.objects
            if ip in subnet.cidr}

        if len(subnet_ids) != 1:
            raise k_exc.IntegrityError(_(
                "Found %(num)s subnets for service %(link)s IP %(ip)s") % {
                    'link': utils.get_res_link(service),
                    'ip': ip,
                    'num': len(subnet_ids)})

        return subnet_ids.pop()

    def create_crd_spec(self, service):
        svc_name = service['metadata']['name']
        svc_namespace = service['metadata']['namespace']
        kubernetes = clients.get_kubernetes_client()
        spec = self._build_kuryrloadbalancer_spec(service)
        loadbalancer_crd = {
            'apiVersion': 'openstack.org/v1',
            'kind': 'KuryrLoadBalancer',
            'metadata': {
                'name': svc_name,
                'finalizers': [k_const.KURYRLB_FINALIZER],
            },
            'spec': spec,
            'status': {},
        }

        try:
            kubernetes.post('{}/{}/kuryrloadbalancers'.format(
                k_const.K8S_API_CRD_NAMESPACES, svc_namespace),
                loadbalancer_crd)
        except k_exc.K8sConflict:
            raise k_exc.ResourceNotReady(svc_name)
        except k_exc.K8sNamespaceTerminating:
            raise
        except k_exc.K8sClientException:
            LOG.exception("Exception when creating KuryrLoadBalancer CRD.")
            raise

    def _update_crd_spec(self, loadbalancer_crd, service):
        svc_name = service['metadata']['name']
        kubernetes = clients.get_kubernetes_client()
        spec = self._build_kuryrloadbalancer_spec(service)
        LOG.debug('Patching KuryrLoadBalancer CRD %s', loadbalancer_crd)
        try:
            kubernetes.patch_crd('spec', utils.get_res_link(loadbalancer_crd),
                                 spec)
        except k_exc.K8sResourceNotFound:
            LOG.debug('KuryrLoadBalancer CRD not found %s', loadbalancer_crd)
        except k_exc.K8sConflict:
            raise k_exc.ResourceNotReady(svc_name)
        except k_exc.K8sClientException:
            LOG.exception('Error updating kuryrnet CRD %s', loadbalancer_crd)
            raise

    def _get_data_timeout_annotation(self, service):
        default_timeout_cli = config.CONF.octavia_defaults.timeout_client_data
        default_timeout_mem = config.CONF.octavia_defaults.timeout_member_data
        try:
            annotations = service['metadata']['annotations']
        except KeyError:
            return default_timeout_cli, default_timeout_mem
        try:
            timeout_cli = annotations[k_const.K8S_ANNOTATION_CLIENT_TIMEOUT]
            data_timeout_cli = int(timeout_cli)
        except KeyError:
            data_timeout_cli = default_timeout_cli
        try:
            timeout_mem = annotations[k_const.K8S_ANNOTATION_MEMBER_TIMEOUT]
            data_timeout_mem = int(timeout_mem)
        except KeyError:
            data_timeout_mem = default_timeout_mem
        return data_timeout_cli, data_timeout_mem

    def _build_kuryrloadbalancer_spec(self, service):
        svc_ip = self._get_service_ip(service)
        spec_lb_ip = service['spec'].get('loadBalancerIP')
        ports = service['spec'].get('ports')
        for port in ports:
            if type(port['targetPort']) == int:
                port['targetPort'] = str(port['targetPort'])
        project_id = self._drv_project.get_project(service)
        sg_ids = self._drv_sg.get_security_groups(service, project_id)
        subnet_id = self._get_subnet_id(service, project_id, svc_ip)
        spec_type = service['spec'].get('type')
        spec = {
            'ip': svc_ip,
            'ports': ports,
            'project_id': project_id,
            'security_groups_ids': sg_ids,
            'subnet_id': subnet_id,
            'type': spec_type
        }

        if spec_lb_ip is not None:
            spec['lb_ip'] = spec_lb_ip
        timeout_cli, timeout_mem = self._get_data_timeout_annotation(service)
        spec['timeout_client_data'] = timeout_cli
        spec['timeout_member_data'] = timeout_mem
        return spec

    def _has_lbaas_spec_changes(self, service, loadbalancer_crd):
        return (self._has_ip_changes(service, loadbalancer_crd) or
                utils.has_port_changes(service, loadbalancer_crd) or
                self._has_timeout_changes(service, loadbalancer_crd))

    def _has_ip_changes(self, service, loadbalancer_crd):
        link = utils.get_res_link(service)
        svc_ip = self._get_service_ip(service)

        if loadbalancer_crd['spec'].get('ip') is None:
            if svc_ip is None:
                return False
            return True

        elif str(loadbalancer_crd['spec'].get('ip')) != svc_ip:
            LOG.debug("LBaaS spec IP %(spec_ip)s != %(svc_ip)s for %(link)s"
                      % {'spec_ip': loadbalancer_crd['spec']['ip'],
                         'svc_ip': svc_ip,
                         'link': link})
            return True

        return False

    def _has_timeout_changes(self, service, loadbalancer_crd):
        link = utils.get_res_link(service)
        cli_timeout, mem_timeout = self._get_data_timeout_annotation(service)

        for spec_value, current_value in [(loadbalancer_crd['spec'].get(
            'timeout_client_data'), cli_timeout), (loadbalancer_crd[
                'spec'].get('timeout_member_data'), mem_timeout)]:
            if not spec_value and not current_value:
                continue
            elif spec_value != current_value:
                LOG.debug("LBaaS spec listener timeout {} != {} for {}".format(
                    spec_value, current_value, link))
                return True

        return False


class EndpointsHandler(k8s_base.ResourceEventHandler):
    """EndpointsHandler handles K8s Endpoints events.

    EndpointsHandler handles K8s Endpoints events and tracks changes in
    LBaaSServiceSpec to update Neutron LBaaS accordingly and to reflect its'
    actual state in LBaaSState.
    """

    OBJECT_KIND = k_const.K8S_OBJ_ENDPOINTS
    OBJECT_WATCH_PATH = "%s/%s" % (k_const.K8S_API_BASE, "endpoints")

    def __init__(self):
        super(EndpointsHandler, self).__init__()
        self._drv_lbaas = drv_base.LBaaSDriver.get_instance()
        # Note(yboaron) LBaaS driver supports 'provider' parameter in
        # Load Balancer creation flow.
        # We need to set the requested load balancer provider
        # according to 'endpoints_driver_octavia_provider' configuration.
        self._lb_provider = None
        if self._drv_lbaas.providers_supported():
            self._lb_provider = 'amphora'
            if (config.CONF.kubernetes.endpoints_driver_octavia_provider
                    != 'default'):
                self._lb_provider = (
                    config.CONF.kubernetes.endpoints_driver_octavia_provider)

    def on_present(self, endpoints, *args, **kwargs):
        ep_name = endpoints['metadata']['name']
        ep_namespace = endpoints['metadata']['namespace']

        k8s = clients.get_kubernetes_client()
        loadbalancer_crd = k8s.get_loadbalancer_crd(endpoints)

        if (not (self._has_pods(endpoints) or (loadbalancer_crd and
                                               loadbalancer_crd.get('status')))
                or k_const.K8S_ANNOTATION_HEADLESS_SERVICE
                in endpoints['metadata'].get('labels', []) or
                utils.is_kubernetes_default_resource(endpoints)):
            LOG.debug("Ignoring Kubernetes endpoints %s",
                      endpoints['metadata']['name'])
            return

        self._ensure_x_endpoints_present(endpoints)

        if loadbalancer_crd is None:
            try:
                self._create_crd_spec(endpoints)
            except k_exc.K8sNamespaceTerminating:
                LOG.warning('Namespace %s is being terminated, ignoring '
                            'Endpoints %s in that namespace.',
                            ep_namespace, ep_name)
                return
        else:
            self._update_crd_spec(loadbalancer_crd, endpoints)

    def _ensure_x_endpoints_present(self, endpoints):
        k8s = clients.get_kubernetes_client()

        ep_name = endpoints['metadata']['name']
        ep_namespace = endpoints['metadata']['namespace']
        try:
            service = k8s.get(utils.get_service_link(endpoints))
        except k_exc.K8sResourceNotFound:
            LOG.debug('Service %s not found.', ep_name)
            return
        except k_exc.K8sClientException:
            LOG.exception('Error retrieving service %s/%s.',
                          ep_namespace, ep_name)
            raise
        annotations = service['metadata'].get('annotations', {})
        x_svc_name = annotations.get(k_const.K8S_ANNOTATION_X_SVC_NAME)
        if not x_svc_name:
            return
        x_endpoints = {
            'apiVersion': 'v1',
            'kind': 'Endpoints',
            'metadata': {
                'name': x_svc_name,
                'namespace': ep_namespace,
            },
            'subsets': [],
        }
        for ss in endpoints.get('subsets', []):
            addresses = ss['addresses']
            x_addresses = []
            for addr in addresses:
                targetRef = addr.get('targetRef')
                if not targetRef:
                    continue
                if targetRef['kind'] != k_const.K8S_OBJ_POD:
                    continue
                pod = self._get_pod(targetRef['namespace'], targetRef['name'])
                pod_annotations = pod['metadata'].get('annotations', {})
                x_vif_name = pod_annotations.get(
                    k_const.K8S_ANNOTATION_X_VIF_NAME)
                if not x_vif_name:
                    continue

                vifs = driver_utils.get_vifs(pod)
                if x_vif_name not in vifs:
                    continue
                vif = vifs[x_vif_name]
                if len(vif.network.subnets.objects) == 0:
                    continue
                ips = vif.network.subnets.objects[0].ips.objects
                if len(ips) == 0:
                    continue
                x_addresses.append({
                    'ip':  str(ips[0].address),
                })
            x_endpoints['subsets'].append({
                'addresses': x_addresses,
                'ports': ss['ports'],
            })
        k8s = clients.get_kubernetes_client()
        try:
            k8s.get(f"{k_const.K8S_API_NAMESPACES}"
                    f"/{ep_namespace}/endpoints/{x_svc_name}")
        except k_exc.K8sResourceNotFound:
            k8s.post(f"{k_const.K8S_API_NAMESPACES}"
                     f"/{ep_namespace}/endpoints", x_endpoints)
            LOG.debug('Created endpoints: %s', x_endpoints['metadata']['name'])
        else:
            k8s.patch('subsets', f"{k_const.K8S_API_NAMESPACES}"
                      f"/{ep_namespace}/endpoints/{x_svc_name}",
                      x_endpoints['subsets'])

    def _get_pod(self, namespace, name):
        k8s = clients.get_kubernetes_client()
        try:
            return k8s.get(f"{k_const.K8S_API_NAMESPACES}"
                           f"/{namespace}/pods/{name}")
        except k_exc.K8sResourceNotFound as ex:
            LOG.exception("Failed to get pod: %s", ex)
            raise

    def on_deleted(self, endpoints, *args, **kwargs):
        self._remove_endpoints(endpoints)

    def _has_pods(self, endpoints):
        ep_subsets = endpoints.get('subsets', [])
        if not ep_subsets:
            return False
        return any(True
                   for subset in ep_subsets
                   if subset.get('addresses', []))

    def _convert_subsets_to_endpointslice(self, endpoints_obj):
        endpointslices = []
        endpoints = []
        subsets = endpoints_obj.get('subsets', [])
        for subset in subsets:
            addresses = subset.get('addresses', [])
            ports = subset.get('ports', [])
            for address in addresses:
                ip = address.get('ip')
                targetRef = address.get('targetRef')
                endpoint = {
                    'addresses': [ip],
                    'conditions': {
                        'ready': True
                    },
                }
                if targetRef:
                    endpoint['targetRef'] = targetRef
                endpoints.append(endpoint)
            endpointslices.append({
                'endpoints': endpoints,
                'ports': ports,
            })

        return endpointslices

    def _create_crd_spec(self, endpoints, spec=None, status=None):
        endpoints_name = endpoints['metadata']['name']
        namespace = endpoints['metadata']['namespace']
        kubernetes = clients.get_kubernetes_client()

        # TODO(maysams): Remove the convertion once we start handling
        # Endpoint slices.
        epslices = self._convert_subsets_to_endpointslice(endpoints)
        if not status:
            status = {}
        if not spec:
            spec = {'endpointSlices': epslices}

        # NOTE(maysams): As the spec may already contain a
        # ports field from the Service, a new endpointslice
        # field is introduced to also hold ports from the
        # Endpoints under the spec.
        loadbalancer_crd = {
            'apiVersion': 'openstack.org/v1',
            'kind': 'KuryrLoadBalancer',
            'metadata': {
                'name': endpoints_name,
                'finalizers': [k_const.KURYRLB_FINALIZER],
            },
            'spec': spec,
            'status': status,
        }

        if self._lb_provider:
            loadbalancer_crd['spec']['provider'] = self._lb_provider

        try:
            kubernetes.post('{}/{}/kuryrloadbalancers'.format(
                k_const.K8S_API_CRD_NAMESPACES, namespace), loadbalancer_crd)
        except k_exc.K8sConflict:
            raise k_exc.ResourceNotReady(loadbalancer_crd)
        except k_exc.K8sNamespaceTerminating:
            raise
        except k_exc.K8sClientException:
            LOG.exception("Exception when creating KuryrLoadBalancer CRD.")
            raise

    def _update_crd_spec(self, loadbalancer_crd, endpoints):
        kubernetes = clients.get_kubernetes_client()
        # TODO(maysams): Remove the convertion once we start handling
        # Endpoint slices.
        epslices = self._convert_subsets_to_endpointslice(endpoints)
        spec = {'endpointSlices': epslices}
        if self._lb_provider:
            spec['provider'] = self._lb_provider
        try:
            kubernetes.patch_crd(
                'spec',
                utils.get_res_link(loadbalancer_crd),
                spec)
        except k_exc.K8sResourceNotFound:
            LOG.debug('KuryrLoadbalancer CRD not found %s', loadbalancer_crd)
        except k_exc.K8sConflict:
            raise k_exc.ResourceNotReady(loadbalancer_crd)
        except k_exc.K8sClientException:
            LOG.exception('Error updating KuryrLoadbalancer CRD %s',
                          loadbalancer_crd)
            raise

        return True

    def _remove_endpoints(self, endpoints):
        kubernetes = clients.get_kubernetes_client()
        lb_name = endpoints['metadata']['name']
        try:
            kubernetes.patch_crd('spec',
                                 utils.get_klb_crd_path(endpoints),
                                 'endpointSlices',
                                 action='remove')
        except k_exc.K8sResourceNotFound:
            LOG.debug('KuryrLoadBalancer CRD not found %s', lb_name)
        except k_exc.K8sUnprocessableEntity:
            LOG.warning('KuryrLoadBalancer %s modified, ignoring.', lb_name)
        except k_exc.K8sClientException:
            LOG.exception('Error updating KuryrLoadBalancer CRD %s', lb_name)
            raise
