=========================
Feather Refactoring Goals
=========================

--------------------------------
first refactor: clean up the api
--------------------------------

Server Framework
~~~~~~~~~~~~~~~~

TCPServer puts each connection in its own coroutine by scheduling
TCPConnection.handle_all()

inheritance trees:
``````````````````

* Server - creates a socket, knows about a port and hostname

  * TCPServer - binds the socket, has a TCPConnection subclass, has an
    accept() loop

  * UDPServer - socket input goes to an on_data method (this doesn't need to be
    production ready any time soon, but develop it alongside TCPServer just to
    make sure the Server level isn't making any extra assumptions)

* TCPConnection - has a RequestHandler subclass, default implementation
  creates RequestHandler instances and calls their handle() method

  * HTTPConnection - parses the request line and headers of requests, does
    KeepAlive on the connection, requires that its RequestHandler be an
    HTTPRequestHandler subclass

* RequestHandler - accepts a file-like object from which it can read the raw
  request text

  * HTTPRequestHandler - parses the request line and headers

HTTP/WSGI Server
~~~~~~~~~~~~~~~~

pretty much the same as it is now, but separated out file-wise from the server
framework.

hard rule: server framework doesn't import from the http/wsgi server


------------------------------------------------------
the unicorn-like refactor (later, eventually, someday)
------------------------------------------------------

* unicorn-like master/worker processes

* unicorn-like signal handling

* both optional via a Server mixin (?)
