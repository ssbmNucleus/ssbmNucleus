"""Shared OpenRouter helpers for the eval lanes: key loading, price table, spend cap.

Trimmed 2026-10-02: the v1 playbook-era coach loop (tool-calling runner, canned
mock backend, v1 system prompts) was deleted with the rest of the v1 lane; it is
in git history. What stays is what the lanes import: `load_api_key`,
`SpendTracker`, `estimate_cost_usd`, `API_URL`, `ENV_PATH`.
"""
import os

API_URL = "https://openrouter.ai/api/v1/chat/completions"
SPEND_HARD_STOP_USD = 4.00

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(EVAL_DIR)), ".env")

# USD per 1M tokens, (prompt, completion). Source: OpenRouter /api/v1/models,
# verified 2026-07-12; only used for a soft spend estimate / hard stop,
# not billing-accurate.
PRICING_PER_1M = {
    # candidate set (all verified to resolve + support tools on OpenRouter)
    "deepseek/deepseek-v4-flash": (0.077, 0.154),
    "z-ai/glm-4.7-flash": (0.06, 0.40),
    "z-ai/glm-5.2": (0.42, 1.32),
    "moonshotai/kimi-k2.7-code": (0.72, 3.50),  # no plain k2.7 on OpenRouter; -code is the only K2.7 variant
    "qwen/qwen3.7-plus": (0.32, 1.28),          # no qwen3.7 flash/mini exists; -plus is the cheap 3.7
    "google/gemini-3.1-flash-lite": (0.25, 1.50),  # no plain 3.1-flash on OpenRouter; -lite is the text+tools variant
    "minimax/minimax-m3": (0.30, 1.20),  # served coach model since 2026-07-14 (blind taste tests, 3-for-3)
    "deepseek/deepseek-v4-pro": (0.43, 0.87),  # selectable coach model (passed SD honesty gate)
    # judge model (NOT in the candidate set; final analysis is done by Claude directly)
    "anthropic/claude-haiku-4.5": (1.00, 5.00),
}


def load_api_key(*, cache=True):
    """OPENROUTER_API_KEY from the environment, else from the repo `.env`.

    The app stores no keys; dev evals read the key from the environment. An
    `op://` reference in `.env` is resolved through 1Password (desktop approval
    prompt) and is never written to disk. `cache` is accepted for old callers
    and ignored. Raises RuntimeError, never printing the value, when unset.
    """
    key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if key and not key.startswith("op://"):
        return key
    if not os.path.exists(ENV_PATH):
        raise RuntimeError(f"OPENROUTER_API_KEY is not set and no .env found at {ENV_PATH}; "
                           "export OPENROUTER_API_KEY (e.g. via `op run`) and retry")
    for line in open(ENV_PATH, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == "OPENROUTER_API_KEY":
            key = v.strip().strip('"').strip("'")
            if key.startswith("op://"):  # 1Password secret reference
                import subprocess
                key = subprocess.run(["op", "read", key], capture_output=True, text=True, check=True).stdout.strip()
            if key:
                return key
    raise RuntimeError(f"OPENROUTER_API_KEY not found in {ENV_PATH}")


def estimate_cost_usd(model, usage):
    """usage: dict with prompt_tokens / completion_tokens (OpenAI-style)."""
    if not usage:
        return 0.0
    pricing = PRICING_PER_1M.get(model)
    if pricing is None:
        return 0.0
    prompt_price, completion_price = pricing
    prompt_tokens = usage.get("prompt_tokens", 0) or 0
    completion_tokens = usage.get("completion_tokens", 0) or 0
    return (prompt_tokens / 1_000_000.0) * prompt_price + \
           (completion_tokens / 1_000_000.0) * completion_price


class SpendTracker:
    def __init__(self, hard_stop=SPEND_HARD_STOP_USD):
        self.hard_stop = hard_stop
        self.total = 0.0

    def add(self, usd):
        self.total += usd
        if self.total > self.hard_stop:
            raise SystemExit(
                f"HARD STOP: cumulative estimated spend ${self.total:.4f} "
                f"exceeded limit ${self.hard_stop:.2f}. Run aborted.")
