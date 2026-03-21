# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.2.x   | :white_check_mark: |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in smolclaw, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, email **magnus.uno.friberg@gmail.com** with:

- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

You will receive an acknowledgment within 48 hours and a detailed response within 7 days.

## Security Considerations

smolclaw runs AI agents with access to local tools and filesystem. Key security considerations:

- **Token storage** — Channel tokens (Telegram, webhooks) are stored in `.env` files under agent directories. These files should not be committed to version control.
- **API authentication** — The REST API supports optional API key authentication. Set `api_key` in `config.yaml` and pass `Authorization: Bearer <key>` headers. Enable this in production.
- **Authorized users** — Telegram channels support `authorized_users` lists in `agent.yaml` to restrict who can interact with agents.
- **Agent sandboxing** — Agents inherit the permissions of the process running `smolclaw up`. Run with least-privilege where possible.
- **Memory isolation** — Agent memory is isolated by default. Cross-agent memory access requires explicit `cross_agent: true` configuration.
