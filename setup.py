#!/usr/bin/env python
# vim: fileencoding=utf8:et:sw=4:ts=8:sts=4

import os
from setuptools import setup


VERSION = (0, 3, 0, "")

setup(
    name="feather-http",
    description="HTTP/WSGI server with coroutines and non-blocking I/O",
    packages=["feather"],
    scripts=["scripts/featherctl"],
    version=".".join(filter(None, map(str, VERSION))),
    author="Travis Parker",
    author_email="travis.parker@gmail.com",
    url="http://github.com/teepark/feather",
    license="BSD",
    classifiers = [
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: BSD License",
        "Natural Language :: English",
        "Programming Language :: Python",
    ],
    install_requires=['greenhouse'],
)
