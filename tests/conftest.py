import os

# Tests use LiteLLM's bundled price list: no network, and no upstream price changes.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
