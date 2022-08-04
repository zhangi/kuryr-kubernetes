import contextlib
from typing import List
from openstack import exceptions as os_exc

from kuryr_kubernetes import utils
from kuryr_kubernetes import clients
from kuryr_kubernetes import constants
from kuryr_kubernetes.handlers import k8s_base
from kuryr_kubernetes import exceptions as k_exc

from oslo_log import log as logging

LOG = logging.getLogger(__name__)


class EndpointsHandler(k8s_base.ResourceEventHandler):
    OBJECT_KIND = constants.K8S_OBJ_ENDPOINTS
    OBJECT_WATCH_PATH = "%s/%s" % (constants.K8S_API_BASE, "endpoints")

    def __init__(self):
        super().__init__()
        self.k8s = clients.get_kubernetes_client()

    def on_present(self, endpoints: dict, *_, **__):
        name = endpoints["metadata"]["name"]
        namespace = endpoints["metadata"]["namespace"]

        try:
            ksg = self.k8s.get_crd(
                "kuryrsecuritygroups", namespace=namespace, name=name
            )
        except k_exc.K8sResourceNotFound:
            LOG.debug("[ep on_present] ksg not found: %s/%s", namespace, name)
            return

        ep_subsets = endpoints.get("subsets", [])
        if ep_subsets == ksg.get("spec", {}).get("endpointSubsets", []):
            LOG.debug(
                "[ep on_present] ksg spec already up to date: %s/%s",
                namespace,
                name,
            )
            return

        try:
            self.k8s.patch_crd(
                "spec",
                utils.get_res_link(ksg),
                {
                    "endpointSubsets": ep_subsets,
                },
            )
            LOG.info(
                "[ep on_present] ksg spec updated %s/%s",
                namespace,
                name,
            )
        except k_exc.K8sResourceNotFound:
            LOG.debug(
                "[ep on_present] ksg not found: %s/%s",
                namespace,
                name,
            )


class SecurityGroupHandler(k8s_base.ResourceEventHandler):
    OBJECT_KIND = constants.K8S_OBJ_SECURITYGROUP
    OBJECT_WATCH_PATH = constants.K8S_API_CRD_KURYRSECGROUP

    def __init__(self):
        super().__init__()
        self.k8s = clients.get_kubernetes_client()
        self.os_net = clients.get_network_client()

    def on_present(self, ksg: dict, *_, **__):
        name = ksg["metadata"]["name"]
        namespace = ksg["metadata"]["namespace"]
        sg_ids: List[str] = ksg.get("spec", {}).get("securityGroupIDs", [])
        subsets: List[dict] = ksg.get("spec", {}).get("endpointSubsets", [])

        if sg_ids == ksg.get("status", {}).get(
            "securityGroupIDs", []
        ) and subsets == ksg.get("status", {}).get("endpointSubsets", []):
            LOG.debug(
                "[ksg on_present] secgroups already up to date: %s/%s",
                namespace,
                name,
            )
            return

        for subset in subsets:
            addresses = subset.get("addresses", []) + subset.get(
                "notReadyAddresses", []
            )
            for address in addresses:
                pod_name = address.get("targetRef", {}).get("name", "")
                try:
                    pod = self.k8s.get_object(
                        "pods",
                        namespace=namespace,
                        name=pod_name,
                    )
                except k_exc.K8sResourceNotFound:
                    LOG.debug(
                        "pod not found for ksg on_present: %s/%s",
                        namespace,
                        name,
                    )
                    continue
                with contextlib.suppress(os_exc.NotFoundException):
                    self._update_pod_vif_sgs(pod, sg_ids)

        self.k8s.patch_crd(
            "status",
            utils.get_res_link(ksg),
            {
                "securityGroupIDs": sg_ids,
                "endpointSubsets": subsets,
            },
        )
        LOG.info(
            "[ksg on_present] ksg status updated %s/%s",
            namespace,
            name,
        )

    def on_finalize(self, ksg: dict, *_, **__):
        name = ksg["metadata"]["name"]
        namespace: str = ksg["metadata"]["namespace"]

        try:
            svc = self.k8s.get_object(
                "services", namespace=namespace, name=name
            )
            self.k8s.remove_finalizer(svc, constants.KURYRSECGROUP_FINALIZER)
            LOG.info("ksg finalizer removed from svc %s/%s", namespace, name)
        except k_exc.K8sResourceNotFound:
            LOG.debug(
                "svc not found for ksg on_finalize: %s/%s", namespace, name
            )

        self.k8s.remove_finalizer(ksg, constants.KURYRSECGROUP_FINALIZER)
        LOG.info("ksg finalizer removed from ksg %s/%s", namespace, name)

    def _update_pod_vif_sgs(self, pod: dict, sg_ids: List[str]):
        pod_name = pod["metadata"]["name"]
        namespace = pod["metadata"]["namespace"]

        kp = self.k8s.get_crd("kuryrports", namespace=namespace, name=pod_name)
        vifs = kp.get("status", {}).get("vifs", {})

        sgs = {
            sg_id: self.os_net.find_security_group(sg_id) for sg_id in sg_ids
        }

        for _, vif in vifs.items():
            port_id = vif["vif"]["versioned_object.data"]["id"]
            port = self.os_net.get_port(port_id)

            valid_sg_ids = {
                sg_id
                for sg_id in sg_ids
                if sgs[sg_id] and sgs[sg_id].project_id == port.project_id
            }
            self.os_net.update_port(
                port_id, security_groups=list(valid_sg_ids)
            )
            LOG.info(
                "ksg applied to port %s in pod %s/%s: %s",
                port_id,
                namespace,
                pod_name,
                valid_sg_ids,
            )


class ServiceHandler(k8s_base.ResourceEventHandler):
    OBJECT_KIND = constants.K8S_OBJ_SERVICE
    OBJECT_WATCH_PATH = "%s/%s" % (constants.K8S_API_BASE, "services")

    def __init__(self):
        super().__init__()
        self.k8s = clients.get_kubernetes_client()

    def on_present(self, svc: dict, *_, **__):
        annotations = svc["metadata"].get("annotations", {})

        if constants.K8S_ANNOTATION_SECGROUP_CRD in annotations:
            self.k8s.add_finalizer(svc, constants.KURYRSECGROUP_FINALIZER)

    def on_finalize(self, svc: dict, *_, **__):
        name = svc["metadata"]["name"]
        namespace = svc["metadata"]["namespace"]

        if constants.KURYRSECGROUP_FINALIZER in svc["metadata"].get(
            "finalizers", {}
        ):
            try:
                self.k8s.del_crd(
                    "kuryrsecuritygroups", namespace=namespace, name=name
                )
                LOG.info("ksg crd deleted: %s/%s", namespace, name)
            except k_exc.K8sResourceNotFound:
                self.k8s.remove_finalizer(
                    svc, constants.KURYRSECGROUP_FINALIZER
                )
                LOG.info(
                    "ksg finalizer removed from svc %s/%s", namespace, name
                )
                return
