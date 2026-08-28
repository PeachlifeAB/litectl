# litectl

A packaged CLI that installs and maintains a local LiteLLM proxy configuration.

## Install locally

```bash
./install.sh
```

The script bootstraps uv when needed, installs the `litectl` wheel as a tool,
and runs `litectl install`. Homebrew, APT, and Pacman packages can expose the
same command without changing the installed layout.

## Installed files

Configuration is written to `$XDG_CONFIG_HOME/litectl`, falling back to
`~/.config/litectl`:

```text
litectl/
├── config.yaml
└── providers/
    ├── cerebras/models.yaml
    └── omlx/models.yaml
```

Defaults come from package resources. Existing configuration and provider records are
preserved on reinstall. Logs and runtime state live under `$XDG_STATE_HOME/litectl`,
falling back to `~/.local/state/litectl`.

## Commands

```bash
litectl install
litectl start
litectl stop
litectl status
litectl logs
litectl list
litectl update
litectl serve
litectl teardown
```

macOS uses a launchd user agent. Linux uses a systemd user service. Other platforms can
run `litectl serve` in the foreground. The managed service watches configuration
files, validates completed edit bursts, and gracefully replaces the LiteLLM child.

Provider discovery is private to install and update. `list` reads recorded state without
contacting provider endpoints. Application upgrades and removal belong to the package
manager that installed the CLI.

### Providers

Any OpenAI-compatible server works the same way: set its `_API_BASE` (and
`_API_KEY` if it requires one), then `litectl update`. Bases are user properties —
example defaults below, never assumptions in code.

| Provider  | Env pair                                   | Example base                           |
| --------- | ------------------------------------------ | -------------------------------------- |
| omlx      | `OMLX_API_BASE` / `OMLX_API_KEY`           | `http://127.0.0.1:8000/v1`             |
| cerebras  | `CEREBRAS_API_BASE` / `CEREBRAS_API_KEY`   | `https://api.cerebras.ai/v1` (default) |
| ollama    | `OLLAMA_API_BASE` / `OLLAMA_API_KEY`       | `http://127.0.0.1:11434/v1`            |
| llama-cpp | `LLAMA_CPP_API_BASE` / `LLAMA_CPP_API_KEY` | `http://127.0.0.1:8080/v1`             |
| lmstudio  | `LMSTUDIO_API_BASE` / `LMSTUDIO_API_KEY`   | `http://127.0.0.1:1234/v1`             |
| ds4       | `DS4_API_BASE` / `DS4_API_KEY`             | `http://127.0.0.1:8029/v1`             |

A provider without a base is reported `no api base configured` and skipped; discovery
never scans ports and never runs provider CLIs. All models route as `openai/<id>`

## Develop

```bash
uv sync
uv run poe validate
uv build
```

The wheel and source distribution are written to `dist/`. Tests inspect the built wheel
and smoke-run its entry point outside the repository checkout.

```bash
OPENAI_API_KEY=... RUN_LOCAL_LLM_TESTS=1 uv run pytest tests/test_local_omlx.py
```
