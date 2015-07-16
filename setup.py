import os
import sys
import subprocess
from distutils.core import setup

from distutils.command.build_py import build_py
from distutils.spawn import find_executable

# Find the Protocol Compiler.
if 'PROTOC' in os.environ and os.path.exists(os.environ['PROTOC']):
    protoc = os.environ['PROTOC']
else:
    protoc = find_executable("protoc")

if protoc is None:
    sys.stderr.write('protoc not found. Is protobuf-compiler installed? \n'
                     'Alternatively, you can point the PROTOC environment variable to protoc executable path.')
    sys.exit(1)

def generate_proto(source, require=True):
    """Invokes the Protocol Compiler to generate a _pb2.py from the given
      .proto file.  Does nothing if the output already exists and is newer than
      the input."""

    if not require and not os.path.exists(source):
        return

    output = source.replace(".proto", "_pb2.py")

    if (not os.path.exists(output) or
          (os.path.exists(source) and
           os.path.getmtime(source) > os.path.getmtime(output))):
        print("Generating %s..." % output)

    if not os.path.exists(source):
        sys.stderr.write("Can't find required file: %s\n" % source)
        sys.exit(-1)

    protoc_command = [protoc, "--python_out=.", source]
    if subprocess.call(protoc_command) != 0:
        sys.exit(-1)

class gen_proto(build_py):
    def run(self):
        # Generate necessary .proto file if it doesn't exist.
        generate_proto("reviewnotify/googleplay/market.proto")
        # build_py is an old-style class, so super() doesn't work.
        build_py.run(self)

setup(
    name='google-play-review-notify',
    packages=[
        'reviewnotify',
        'reviewnotify.googleplay',
        "twisted.plugins",
    ],
    cmdclass={'gen_proto': gen_proto},
    package_data={'reviewnotify': ['templates/*.txt',
                                   'locales/en_US/LC_MESSAGES/messages.mo',
                                   'locales/ru_RU/LC_MESSAGES/messages.mo']},
    include_package_data=True,
    version='0.1.0',

    url='https://github.com/3cky/google-play-review-notify',
    author='Victor Antonovich',
    author_email='victor@antonovich.me',
)

# Make Twisted regenerate the dropin.cache, if possible.  This is necessary
# because in a site-wide install, dropin.cache cannot be rewritten by
# normal users.
try:
    from twisted.plugin import IPlugin, getPlugins
except ImportError:
    pass
else:
    list(getPlugins(IPlugin))
