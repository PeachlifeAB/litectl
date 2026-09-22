"""Default config.yaml for a workspace that has none.

Kept as data so the adapter that writes it stays about YAML, not content.
"""

from __future__ import annotations

SEED_CONFIG = """---
include:
  - ./providers/cerebras/models.yaml
  - ./providers/omlx/models.yaml

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY

router_settings:
  routing_strategy: usage-based-routing
  enable_pre_call_checks: true
  num_retries: 1
  timeout: 600
  allowed_fails: 1
  cooldown_time: 20

  model_group_alias:
    default_cloud: &cloud cerebras-gpt-oss-120b
    default: *cloud

litellm_settings:
  drop_params: true
  callbacks:
    - litectl_hooks.handler

model_list: []
"""
