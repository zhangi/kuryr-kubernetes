import contextlib
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
            ksp = self.k8s.get_crd(
                "kuryrsecuritygroups", namespace=namespace, name=name
            )
            self.k8s.patch_crd(
                "status",
                utils.get_res_link(ksp),
                {
                    "endpointResourceVersoin": endpoints["metadata"][
                        "resourceVersion"
                    ]
                },
            )
            LOG.info(
                "ksg crd updated by ep %s/%s: resourceVersion %s",
                namespace,
                name,
                endpoints["metadata"]["resourceVersion"],
            )
        except k_exc.K8sResourceNotFound:
            LOG.debug("ksg not found for ep: %s/%s", namespace, name)


class SecurityGroupHandler(k8s_base.ResourceEventHandler):
    OBJECT_KIND = constants.K8S_OBJ_SECURITYGROUP
    OBJECT_WATCH_PATH = constants.K8S_API_CRD_KURYRSECGROUP

    def __init__(self):
        super().__init__()
        self.k8s = clients.get_kubernetes_client()
        self.os_net = clients.get_network_client()

    def on_present(self, ksg: dict, *_, **__):
        name = ksg["spec"]["endpointName"]
        namespace = ksg["metadata"]["namespace"]
        sg_ids: [str] = ksg["status"]["securityGroupIDs"]

        try:
            eps = self.k8s.get_object(
                "endpoints", namespace=namespace, name=name
            )
        except k_exc.K8sResourceNotFound:
            LOG.debug(
                "[ksg on_present] ep for ksg not found: %s/%s",
                namespace,
                name,
            )
            return

        for subset in eps["subsets"]:
            addresses = subset.get("addresses", []) + subset.get(
                "notReadyAddresses", []
            )
            for address in addresses:
                try:
                    pod_name = address["targetRef"]["name"]
                except KeyError:
                    continue
                try:
                    pod = self.k8s.get_object(
                        "pods",
                        namespace=namespace,
                        name=pod_name,
                    )
                except k_exc.K8sResourceNotFound:
                    continue
                with contextlib.suppress(os_exc.NotFoundException):
                    self._update_pod_vif_sgs(pod, sg_ids)

    def on_finalize(self, ksg: dict, *_, **__):
        name = ksg["spec"]["endpointName"]
        namespace: str = ksg["metadata"]["namespace"]

        try:
            eps = self.k8s.get_object(
                "endpoints", namespace=namespace, name=name
            )
        except k_exc.K8sResourceNotFound:
            LOG.debug(
                "[ksg on_finalize] ep for ksg not found: %s/%s",
                namespace,
                name,
            )
            self.k8s.remove_finalizer(ksg, constants.KURYRSECGROUP_FINALIZER)
            LOG.info("ksg finalizer removed from ksg %s/%s", namespace, name)
            return

        for subset in eps["subsets"]:
            addresses = subset.get("addresses", []) + subset.get(
                "notReadyAddresses", []
            )
            for address in addresses:
                pod = self.k8s.get_object(
                    "pods",
                    namespace=namespace,
                    name=address["targetRef"]["name"],
                )
                with contextlib.suppress(os_exc.NotFoundException):
                    self._update_pod_vif_sgs(pod, [])

        with contextlib.suppress(k_exc.K8sResourceNotFound):
            svc = self.k8s.get_object(
                "services", namespace=namespace, name=name
            )
            self.k8s.remove_finalizer(svc, constants.KURYRSECGROUP_FINALIZER)
            LOG.info("ksg finalizer removed from svc %s/%s", namespace, name)

        self.k8s.remove_finalizer(ksg, constants.KURYRSECGROUP_FINALIZER)
        LOG.info("ksg finalizer removed from ksg %s/%s", namespace, name)

    def _update_pod_vif_sgs(self, pod: dict, sg_ids: [str]):
        pod_name = pod["metadata"]["name"]
        namespace = pod["metadata"]["namespace"]

        kp = self.k8s.get_crd("kuryrports", namespace=namespace, name=pod_name)
        vifs = kp["status"]["vifs"]

        sgs = {
            sg_id: self.os_net.find_security_group(sg_id) for sg_id in sg_ids
        }

        for name, vif in vifs.items():
            port_id = vif["vif"]["versioned_object.data"]["id"]
            network_id = vif["vif"]["versioned_object.data"]["network"][
                "versioned_object.data"
            ]["id"]
            network = self.os_net.find_network(network_id)
            valid_sg_ids = {
                sg_id
                for sg_id in sg_ids
                if sgs[sg_id].project_id == network.project_id
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
        name = svc["metadata"]["name"]
        namespace = svc["metadata"]["namespace"]
        annotations = svc["metadata"].get("annotations", {})

        if constants.K8S_ANNOTATION_SECGROUP_CRD in annotations:
            self.k8s.add_finalizer(svc, constants.KURYRSECGROUP_FINALIZER)
            LOG.info(
                "ksg finalizer added to svc %s/%s",
                namespace,
                name,
            )

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
