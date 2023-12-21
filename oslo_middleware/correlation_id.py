# Copyright (c) 2013 Rackspace Hosting
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

from __future__ import annotations

import typing as ty

from oslo_utils import uuidutils

from oslo_middleware import base

if ty.TYPE_CHECKING:
    import webob.request
    import webob.response


class CorrelationId(base.ConfigurableMiddleware):
    "Middleware that attaches a correlation id to WSGI request"

    @staticmethod
    def process_request(
        req: webob.request.Request,
    ) -> webob.response.Response | None:
        correlation_id = (
            req.headers.get("X_CORRELATION_ID") or uuidutils.generate_uuid()
        )
        req.headers['X_CORRELATION_ID'] = correlation_id
        return None
