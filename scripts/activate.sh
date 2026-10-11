# Source from the repository root: source scripts/activate.sh
# Supports bash and zsh. Keeps downloaded tooling inside this project.
if [ ! -f .venv/bin/activate ] || [ ! -x .tools/node/bin/node ]; then
  printf '%s\n' 'Run environment setup from the project root before activation.' >&2
  return 1
fi
. .venv/bin/activate
export PATH="$PWD/.tools/node/bin:$PWD/.tools/bin:$PATH"
export PIP_CACHE_DIR="$PWD/.tools/pip-cache"
export PIP_CERT="$PWD/.tools/cacert.pem"
export SSL_CERT_FILE="$PWD/.tools/cacert.pem"
export NODE_EXTRA_CA_CERTS="$PWD/.tools/cacert.pem"
export npm_config_cache="$PWD/.tools/npm-cache"
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.tools/playwright"
