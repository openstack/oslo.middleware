# Copyright 2024 Red Hat.
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

from oslo_middleware.healthcheck import opts
from oslo_middleware.healthcheck import pluginbase

LOG = logging.getLogger(__name__)


class EnableByFilesHealthcheck(pluginbase.HealthcheckBaseExtension):
    """EnableByFilesHealthcheck healthcheck middleware plugin

    This plugin checks presence of a file at a specified location.

    Example of middleware configuration:

    .. code-block:: ini

      [app:healthcheck]
      paste.app_factory = oslo_middleware:Healthcheck.app_factory
      path = /healthcheck
      backends = enable_by_files
      enable_by_file_paths = /var/lib/glance/images/.marker,
          /var/lib/glance/os_glance_staging_store/.marker
      # set to True to enable detailed output, False is the default
      detailed = False
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.oslo_conf.register_opts(opts.ENABLE_BY_FILES_OPTS,
                                     group='healthcheck')
        self.file_paths = self._conf_get('enable_by_file_paths')

    def healthcheck(self, server_port):
        for file_path in self.file_paths:
            if not os.path.exists(file_path):
                LOG.warning('EnableByFiles healthcheck middleware: Path %s '
                            'is not present', file_path)
                return pluginbase.HealthcheckResult(
                    available=False, reason="FILE PATH MISSING",
                    details='File path %s is missing' % file_path)
        return pluginbase.HealthcheckResult(
            available=True, reason="OK",
            details='Specified file paths are available')
