<# Portainer MCP Server — Requirements Document

## Project Overview

MCP server providing Claude/Copilot with programmatic access to the Portainer infrastructure management API (`https://pr.local.defaultvaluation.com`). Enables container and Docker resource automation through AI agents.

---

## Functional Requirements

### 1. API Integration
- Implement Portainer API client with JWT Bearer token authentication.
- Support core operations: container management, image operations, stack deployment, volume management.

### 2. Secure Token Storage
- Store Portainer access token encrypted in macOS Keychain using the `security` command-line tool.
- Token must be retrieved at runtime without plaintext exposure.

### 3. MCP Tool Definitions
Expose minimum 8 tools, each with proper input schema and error handling:

| Tool | Description |
|---|---|
| `list_containers` | List all containers on an endpoint |
| `inspect_container` | Get detailed info for a specific container |
| `list_images` | List Docker images on an endpoint |
| `list_stacks` | List all deployed stacks |
| `deploy_stack` | Deploy or update a Docker stack |
| `stop_container` | Stop a running container |
| `start_container` | Start a stopped container |
| `container_logs` | Retrieve logs from a container |
| `health_check` | Validate Portainer connectivity and token validity |

### 4. Environmental Configuration
- Load Portainer endpoint URL from encrypted Keychain or environment variables.
- Support multiple Portainer instances with named configurations.

---

## Non-Functional Requirements

### 5. Security
- Defense-in-depth: input validation/sanitization, schema enforcement, least-privilege API permissions.
- Never log or expose tokens in stdout.

### 6. Authentication & Authorization
- Bearer token validation on every Portainer API call.
- Respect Portainer user RBAC permissions.
- Propagate authorization errors clearly to LLM agent.

### 7. Error Handling
- Graceful degradation for API failures, network timeouts, and permission-denied scenarios.
- Return structured error messages with actionable context.

### 8. Logging
- Structured JSON logging (no sensitive data).
- Log API requests/responses (excluding token values), errors, and performance metrics.
- Output to stdout for Claude/client capture.

---

## Technical Specifications

### 9. Language
- Python 3.10+ with MCP SDK (latest stable).
- Use `async`/`await` patterns for all I/O operations.

### 10. macOS Keychain Integration
- Use `subprocess` + `security` CLI for Keychain access (retrieve/store).
- Alternative: `keyring` library with macOS backend for abstraction.

### 11. HTTPS Communication
- Verify Portainer's self-signed certificate where applicable.
- Implement configurable SSL verification (disabled only in non-production).

### 12. Dependencies

| Package | Purpose |
|---|---|
| `httpx` | Async HTTP client |
| `pydantic` | Schema validation |
| `keyring` | Optional macOS Keychain abstraction |
| `mcp` | MCP SDK tools and resources decorators |

---

## Quality & Testing

### 13. Type Safety
- Use type hints throughout.
- Validate all inputs with Pydantic models matching Portainer API schema.

### 14. Testing
- Unit tests for Keychain storage/retrieval, API client mocking, tool parameter validation.
- Integration test against test Portainer instance or sandbox.

### 15. Documentation
- Inline docstrings for all tools.
- Setup guide (Keychain configuration, environment initialization).
- Example usage patterns.

---

## Deployment & Operations

### 16. Configuration as Code
- Use `~/.config/portainer-mcp/config.yaml` or environment variables for initialization.
- Document all required settings with secure defaults.

### 17. Runtime Isolation
- Run as dedicated process with restricted Keychain access.
- Support Claude desktop client and CI/CD environments (token via env var fallback).

### 18. Health Check
- Implement `status`/`health` tool to validate Portainer connectivity and token validity without triggering operations.

---

## References

1. Portainer API documentation. (2026). *Accessing the Portainer API*. https://docs.portainer.io/api/docs
2. GitHub - portainer/portainer-docs. (2024). *API access and authentication*. https://github.com/portainer/portainer-docs/blob/2.21/api/access.md
3. Apple Support. (2025). *Keychain data protection*. https://support.apple.com/guide/security/keychain-data-protection-secb0694df1a/web
4. eclecticlight.co. (2023). *An introduction to keychains and how they've changed*. https://eclecticlight.co/2023/08/07/an-introduction-to-keychains-and-how-theyve-changed/
5. OWASP GenAI. (2026). *A Practical Guide for Secure MCP Server Development*. https://genai.owasp.org/resource/a-practical-guide-for-secure-mcp-server-development/
6. Merge.dev. (2025). *3 insider tips for using the Model Context Protocol effectively*. https://www.merge.dev/blog/mcp-best-practices
