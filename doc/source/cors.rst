===============
CORS Middleware
===============

This middleware provides a comprehensive, configurable implementation of the
CORS_ (Cross Origin Resource Sharing) specification as oslo-supported python
wsgi middleware.

.. note::

   While this middleware supports the use of the `*` wildcard origin in the
   specification, this feature is not recommended for security reasons. It
   is provided to simplify basic use of CORS, practically meaning "I don't
   care how this is used." In an intranet setting, this could lead to leakage
   of data beyond the intranet and therefore should be avoided.

Quickstart
----------
First, include the middleware in your application::

    from oslo_middleware import cors
    from oslo_config import cfg

    app = cors.CORS(your_wsgi_application, cfg.CONF)

Secondly, add a global [cors] configuration block to the configuration file
read by oslo.config::

    [cors]
    allowed_origin=https://website.example.com:443
    max_age=3600
    allow_methods=GET,POST,PUT,DELETE
    allow_headers=Content-Type,Cache-Control,Content-Language,Expires,Last-Modified,Pragma,X-Custom-Header
    expose_headers=Content-Type,Cache-Control,Content-Language,Expires,Last-Modified,Pragma,X-Custom-Header

Advanced Configuration
----------------------
CORS Middleware permits you to define multiple `allowed_origin`'s, and to
selectively override the global configuration for each. To accomplish this,
first follow the setup instructions in the Quickstart above.

Then, create an new configuration group for each domain that you'd like to
extend. Each of these configuration groups must be named `[cors.something]`,
with each name being unique. The purpose of the suffix to `cors.` is
legibility, we recommend using a reasonable human-readable string::

    [cors.ironic_webclient]
    # CORS Configuration for a hypothetical ironic webclient, which overrides
    # authentication
    allowed_origin=https://ironic.example.com:443
    allow_credentials=True

    [cors.horizon]
    # CORS Configuration for horizon, which uses global options.
    allowed_origin=https://horizon.example.com:443

    [cors.wildcard]
    # CORS Configuration for the CORS specified domain wildcard, which only
    # permits HTTP GET requests.
    allowed_origin=*
    allow_methods=GET


Module Documentation
--------------------

.. automodule:: oslo_middleware.cors
   :members:

.. _CORS: http://www.w3.org/TR/cors/
