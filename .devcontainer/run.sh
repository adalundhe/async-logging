
if [[ ! -d /workspace/.venv ]]; then
    uv venv
fi

source .venv/bin/activate

