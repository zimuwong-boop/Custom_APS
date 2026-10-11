#!/bin/sh
# Recreate the verified local tooling from the committed dependency locks.
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"
python_command=${PYTHON_COMMAND:-python3}
if [ ! -x .venv/bin/python ]; then
  "$python_command" -m venv .venv
fi
mkdir -p .tools
.venv/bin/python -c 'from pathlib import Path; import shutil; from pip._vendor import certifi; shutil.copyfile(certifi.where(), Path(".tools/cacert.pem"))'
.venv/bin/python -c 'from pathlib import Path; Path(".venv/pip.conf").write_text("[global]\ncert = " + str(Path(".tools/cacert.pem").resolve()) + "\ncache-dir = " + str(Path(".tools/pip-cache").resolve()) + "\n")'
export PIP_CACHE_DIR="$project_root/.tools/pip-cache"
export PIP_CERT="$project_root/.tools/cacert.pem"
export SSL_CERT_FILE="$project_root/.tools/cacert.pem"
.venv/bin/python -m pip install --upgrade pip==26.2.1
.venv/bin/python -m pip install --require-hashes -r requirements/dev.txt
if [ ! -x .tools/node/bin/node ]; then
  .venv/bin/python scripts/install_node.py
fi
mkdir -p .tools/bin
if [ -x /Applications/Docker.app/Contents/Resources/bin/docker ] && [ ! -e .tools/bin/docker ]; then
  ln -s /Applications/Docker.app/Contents/Resources/bin/docker .tools/bin/docker
fi
./scripts/npm ci
./scripts/npm exec playwright install chromium
printf '%s\n' 'Environment ready. From the project root: source scripts/activate.sh'
