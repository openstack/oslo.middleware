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

from __future__ import annotations

import abc
import typing as ty

if ty.TYPE_CHECKING:
    from oslo_config import cfg


class HealthcheckResult:
    """Result of a ``healthcheck`` method call should be this object."""

    def __init__(
        self,
        available: bool,
        reason: str,
        details: str | None = None,
    ) -> None:
        self.available = available
        self.reason = reason
        self.details = details


class HealthcheckBaseExtension(metaclass=abc.ABCMeta):
    def __init__(
        self,
        oslo_conf: cfg.ConfigOpts,
        conf: dict[str, ty.Any],
    ) -> None:
        self.oslo_conf = oslo_conf
        self.conf = conf

    @abc.abstractmethod
    def healthcheck(self, server_port: int) -> HealthcheckResult:
        """method called by the healthcheck middleware

        return: HealthcheckResult object
        """

    def _conf_get(self, key: str, group: str = 'healthcheck') -> ty.Any:
        if key in self.conf:
            # Validate value type
            self.oslo_conf.set_override(key, self.conf[key], group=group)
        return getattr(getattr(self.oslo_conf, group), key)
