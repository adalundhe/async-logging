
if [[ ! -d /workspace/.venv ]]; then
    uv venv
fi

source .venv/bin/activate
uv pip install -r requirements.txt
uv pip install -e .