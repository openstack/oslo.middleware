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

import logging
import os

from oslo_middleware.healthcheck import pluginbase
from oslo_middleware.i18n import _LW

LOG = logging.getLogger(__name__)


class DisableByFileHealthcheck(pluginbase.HealthcheckBaseExtension):
    def healthcheck(self):
        path = self.conf.get('disable_by_file_path')
        if path is None:
            LOG.warning(_LW('DisableByFile healthcheck middleware enabled '
                            'without disable_by_file_path set'))
            return pluginbase.HealthcheckResult(available=True,
                                                reason="")
        elif not os.path.exists(path):
            return pluginbase.HealthcheckResult(available=True,
                                                reason="")
        else:
            return pluginbase.HealthcheckResult(available=False,
                                                reason="DISABLED BY FILE")
