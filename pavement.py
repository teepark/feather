from paver.easy import *
from paver.path import path
from paver.setuputils import setup


setup(
    name="feather-http",
    description="Server building blocks with coroutines and non-blocking I/O",
    packages=["feather"],
    version="0.1.0",
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

MANIFEST = (
    "setup.py",
    "paver-minilib.zip",
)

@task
def manifest():
    path('MANIFEST.in').write_lines('include %s' % x for x in MANIFEST)

@task
@needs('generate_setup', 'minilib', 'manifest', 'setuptools.command.sdist')
def sdist():
    pass

@task
def clean():
    for p in map(path, ('feather.egg-info', 'dist', 'build', 'MANIFEST.in')):
        if p.exists():
            if p.isdir():
                p.rmtree()
            else:
                p.remove()
    for p in path(__file__).abspath().parent.walkfiles():
        if p.endswith(".pyc") or p.endswith(".pyo"):
            p.remove()

@task
def test():
    sh("nosetests")

@task
@needs('install', 'clean', 'test')
def refresh():
    pass

@task
def docs():
    sh("find docs/source/feather -name *.rst | xargs touch")
    sh("cd docs; make html")
