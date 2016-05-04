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

    app = cors.CORS(your_wsgi_application)

Secondly, add as many allowed origins as you would like::

    app.add_origin(allowed_origin='https://website.example.com:443',
                   allow_credentials=True,
                   max_age=3600,
                   allow_methods=['GET','PUT','POST','DELETE'],
                   allow_headers=['X-Custom-Header'],
                   expose_headers=['X-Custom-Header'])

    # ... add more origins here.


Configuration for oslo_config
-----------------------------

A factory method has been provided to simplify configuration of your CORS
domain, using oslo_config::

    from oslo_middleware import cors
    from oslo_config import cfg

    app = cors.CORS(your_wsgi_application, cfg.CONF)

In your application's config file, then include a default configuration block
something like this::

    [cors]
    allowed_origin=https://website.example.com:443,https://website2.example.com:443
    max_age=3600
    allow_methods=GET,POST,PUT,DELETE
    allow_headers=X-Custom-Header
    expose_headers=X-Custom-Header

This middleware permits you to override the rules for multiple
`allowed_origin`'s. To express this in your configuration file, first begin
with a `[cors]` group as above, into which you place your default
configuration values. Then add as many additional configuration groups as
necessary, naming them `[cors.something]` (each name must be unique). The
purpose of the suffix to `cors.` is legibility, we recommend using a
reasonable human-readable string::

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

If your software requires specific headers or methods for proper operation, you
may include these as latent properties. These will be evaluated in addition
to any found in configuration::

    from oslo_middleware import cors

    app = cors.CORS(your_wsgi_application)
    app.set_latent(allow_headers=['X-System-Header'],
                   expose_headers=['X-System-Header'],
                   allow_methods=['GET','PATCH'])


Configuration for pastedeploy
-----------------------------

If your application is using pastedeploy, the following configuration block
will add CORS support.::

    [filter:cors]
    paste.filter_factory = oslo_middleware.cors:filter_factory
    allowed_origin=https://website.example.com:443,https://website2.example.com:443
    max_age=3600
    allow_methods=GET,POST,PUT,DELETE
    allow_headers=X-Custom-Header
    expose_headers=X-Custom-Header

If your application is using pastedeploy, but would also like to use the
existing configuration from oslo_config in order to simplify the points of
configuration, this may be done as follows.::

    [filter:cors]
    paste.filter_factory = oslo_middleware.cors:filter_factory
    oslo_config_project = oslo_project_name

    # Optional field, in case the program name is different from the project:
    oslo_config_program = oslo_project_name-api

    # This method also permits setting latent properties, for any origins set
    # in oslo config.
    latent_allow_headers=X-Auth-Token
    latent_expose_headers=X-Auth-Token
    latent_methods=GET,PUT,POST

Configuration Options
---------------------

.. show-options:: oslo.middleware.cors

Module Documentation
--------------------

.. automodule:: oslo_middleware.cors
   :members:

.. _CORS: http://www.w3.org/TR/cors/
