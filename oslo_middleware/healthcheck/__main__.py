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

import argparse
from http import server
import socketserver
import typing as ty

import webob

from oslo_middleware import healthcheck

if ty.TYPE_CHECKING:
    import webob.request


class HttpHandler(server.SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        @webob.dec.wsgify
        def dummy_application(req: webob.request.Request) -> str:
            return 'test'

        app = healthcheck.Healthcheck(dummy_application, {'detailed': True})
        req = webob.Request.blank(
            "/healthcheck", accept='text/html', method='GET'
        )
        res = req.get_response(app)
        self.send_response(res.status_code)
        for header_name, header_value in res.headerlist:
            self.send_header(header_name, header_value)
        self.end_headers()
        self.wfile.write(res.body)
        self.wfile.close()


def positive_int(blob: str) -> int:
    value = int(blob)
    if value < 0:
        msg = f"{blob!r} is not a positive integer"
        raise argparse.ArgumentTypeError(msg)
    return value


def create_server(port: int = 0) -> socketserver.TCPServer:
    handler = HttpHandler
    server = socketserver.TCPServer(("", port), handler)
    return server


def main(args: ty.Sequence[str] | None = None) -> None:
    """Runs a basic http server to show healthcheck functionality."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-p",
        "--port",
        help="Unused port to run the tiny"
        " http server on (or zero to select a"
        " random unused port)",
        type=positive_int,
        required=True,
    )
    parsed_args = parser.parse_args(args=args)
    server = create_server(parsed_args.port)
    print(f"Serving at port: {server.server_address[1]}")
    server.serve_forever()


if __name__ == '__main__':
    main()
