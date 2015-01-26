# Copyright 2011 OpenStack Foundation.
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

import stevedore
import webob.dec
import webob.exc
import webob.response

from oslo_middleware import base


class Healthcheck(base.Middleware):
    """Healthcheck middleware used for monitoring.

    If the path is /healthcheck, it will respond 200 with "OK" as the body.
    Or 503 with the reason as the body if one of the backend report
    an application issue.

    Example of paste configuration:

    .. code-block:: ini

        [filter:healthcheck]
        paste.filter_factory = oslo_middleware:Healthcheck.factory
        path = /healthcheck
        backends = disable_by_file
        disable_by_file_path = /var/run/nova/healthcheck_disable

        [pipeline:public_api]
        pipeline = healthcheck sizelimit [...] public_service


    Multiple filter sections can be defined if it desired to have
    pipelines with different healthcheck configuration, example:

    .. code-block:: ini

        [pipeline:public_api]
        pipeline = healthcheck_public sizelimit [...] public_service

        [pipeline:admin_api]
        pipeline = healthcheck_admin sizelimit [...] admin_service

        [filter:healthcheck_public]
        paste.filter_factory = oslo_middleware:Healthcheck.factory
        path = /healthcheck_public
        backends = disable_by_file
        disable_by_file_path = /var/run/nova/healthcheck_public_disable

        [filter:healthcheck_admin]
        paste.filter_factory = oslo_middleware:Healthcheck.factory
        path = /healthcheck_admin
        backends = disable_by_file
        disable_by_file_path = /var/run/nova/healthcheck_admin_disable

    More details on available backends and their configuration can be found
    on this page: :doc:`healthcheck_plugins`.

    """

    NAMESPACE = "oslo.middleware.healthcheck"

    @classmethod
    def factory(cls, global_conf, **local_conf):
        """Factory method for paste.deploy."""
        conf = global_conf.copy()
        conf.update(local_conf)

        def healthcheck_filter(app):
            return cls(app, conf)
        return healthcheck_filter

    def __init__(self, application, conf):
        super(Healthcheck, self).__init__(application)
        self._path = conf.get('path', '/healthcheck')
        self._backend_names = []
        backends = conf.get('backends')
        if backends:
            self._backend_names = backends.split(',')

        self._backends = stevedore.NamedExtensionManager(
            self.NAMESPACE, self._backend_names,
            name_order=True, invoke_on_load=True,
            invoke_args=(conf,))

    @webob.dec.wsgify
    def process_request(self, req):
        if req.path != self._path:
            return None

        healthy = True
        reasons = []
        for ext in self._backends:
            result = ext.obj.healthcheck()
            healthy &= result.available
            if result.reason:
                reasons.append(result.reason)

        return webob.response.Response(
            status=(webob.exc.HTTPOk.code if healthy
                    else webob.exc.HTTPServiceUnavailable.code),
            body='\n'.join(reasons),
            content_type="text/plain",
        )
