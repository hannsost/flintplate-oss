# FlintPlate AI providers

The backend uses `langchain_openai.ChatOpenAI` through `app/ai/client.py` with the
OpenAI-compatible Chat Completions interface. The environment names are compatibility
names, not a requirement to use OpenAI. Only features using this shared client are covered;
local embeddings and deterministic table suggestions are separate mechanisms.

| Provider | `OPENAI_BASE_URL` | Example `OPENAI_MODEL` | Key |
| --- | --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` (or unset) | `gpt-4o-mini` | Required |
| Mistral | `https://api.mistral.ai/v1` | `mistral-small-latest` | Required |
| OpenRouter | `https://openrouter.ai/api/v1` | `openai/gpt-4o-mini` | Required |
| Ollama | `http://127.0.0.1:11434/v1` | `llama3.2` | Optional locally |
| LM Studio | `http://127.0.0.1:1234/v1` | Your loaded model ID | Depends on server auth |
| vLLM | `http://127.0.0.1:8000/v1` | Your served model ID | Depends on server auth |


Model IDs are examples, not guarantees of availability. Choose a model served by your endpoint.
Models used for structured extraction must support the response format that the feature requests.
No provider has been contacted as part of staging validation.

```dotenv
# Offline/demo: no remote client is constructed
AI_MOCK_MODE=true
OPENAI_API_KEY=
OPENAI_BASE_URL=
OPENAI_MODEL=gpt-4o-mini
AI_MAX_TOKENS=1500
AI_REQUESTS_PER_MIN=20
```

```dotenv
# Local Ollama (download/serve the model separately)
AI_MOCK_MODE=false
OPENAI_BASE_URL=http://127.0.0.1:11434/v1
OPENAI_API_KEY=
OPENAI_MODEL=llama3.2
```

For hosted services, set `AI_MOCK_MODE=false`, the provider URL/model from the table and
inject `OPENAI_API_KEY` through your secret manager. Never commit the key.
For LM Studio and vLLM, use their URL and loaded/served model from the table; supply a key
only if authentication is enabled. A missing key with a custom base URL uses the dummy
SDK key `ollama`; it is not a credential and does not bypass server authentication.
A missing key **without** a base URL returns no client, so no default vendor is contacted.
Mock mode also returns no client, allowing each feature's existing fallback.

Inside containers, `127.0.0.1` means that container, not the host. Configure an explicit
reachable inference-service hostname or host gateway for local inference. vLLM's default
port may overlap a native API process; choose distinct host ports.

Only send data approved for that provider. Review guest/CV/employee data, retention and
processing location before enabling remote features. The app does not inherit FireFlint's
provider-host allowlist: control egress and protect local model endpoints in deployment.
Initialization errors return the fallback and log the exception type without credentials.

Run offline contracts: `cd backend && python3 -m unittest discover -s unit_tests -v`.
