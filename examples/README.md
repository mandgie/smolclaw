# smolclaw examples

A complete two-agent setup demonstrating smolclaw's core features.

## What's Included

```
examples/
├── config.yaml                    # Gateway config (host, port, log level)
├── agents/
│   ├── tars/                      # Personal assistant agent
│   │   ├── agent.yaml             # Model: Opus, Telegram channel, cross-agent memory
│   │   ├── soul.md                # Personality: direct, dry humor, action-first
│   │   ├── agents.md              # Operational rules: email, calendar, tasks
│   │   └── prompts/
│   │       └── morning-briefing.md  # Cron job template: daily summary
│   └── coach/                     # Fitness trainer agent
│       ├── agent.yaml             # Model: Sonnet, Telegram channel, isolated memory
│       ├── soul.md                # Personality: motivating, practical, evidence-based
│       ├── agents.md              # Operational rules: workouts, nutrition
│       └── prompts/
│           └── daily-checkin.md   # Cron job template: daily workout prompt
├── shared/
│   ├── USER.md                    # Shared user context (all agents see this)
│   └── cron/
│       └── jobs.json              # Two scheduled jobs (morning briefing + daily checkin)
```

## How to Use

### 1. Copy to your smolclaw home

```bash
# Create your smolclaw directory
mkdir -p ~/.smolclaw

# Copy the example setup
cp -r examples/* ~/.smolclaw/
```

### 2. Customize for yourself

Edit `~/.smolclaw/shared/USER.md` with your own info:

```markdown
# User

## Identity
- Name: Jane Smith
- Location: San Francisco, CA
- Timezone: PST (UTC-8)

## Communication Preferences
- Concise and direct.
- Prefers actionable outputs over explanations.
```

### 3. Set up Telegram (optional)

Each agent can have its own Telegram bot. To set one up:

1. Message [@BotFather](https://t.me/botfather) on Telegram
2. Create a new bot — you'll get a token like `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`
3. Create an env file for the agent:

```bash
echo "TARS_TELEGRAM_TOKEN=your-token-here" > ~/.smolclaw/agents/tars/channels/telegram.env
```

4. (Optional) Restrict who can message the bot by adding your Telegram user ID to `agent.yaml`:

```yaml
channels:
  telegram:
    token_env: TARS_TELEGRAM_TOKEN
    authorized_users: [123456789]
```

### 4. Start the gateway

```bash
smolclaw up
```

This boots both agents, starts the Telegram polling (if tokens are set), the cron scheduler, and the REST API at `http://localhost:7890`.

### 5. Try the chat REPL

No Telegram? Chat directly from your terminal:

```bash
smolclaw chat tars
smolclaw chat coach
```

## Key Concepts Demonstrated

### Multi-agent isolation
- **tars** uses Opus (smarter, more expensive) for complex tasks
- **coach** uses Sonnet (faster, cheaper) for simpler interactions
- Each agent has its own personality, rules, and tool access

### Cross-agent memory
- tars has `cross_agent: true` — can search coach's memory too
- coach has `cross_agent: false` — only sees its own data
- Both share the same SQLite database (`shared/memory.db`)

### Scheduled jobs
- `tars-morning-briefing`: weekdays at 08:00, delivered to Telegram
- `coach-daily-checkin`: daily at 07:00, delivered to Telegram
- Jobs route through the same message bus as everything else

### Progressive skill disclosure
- Add skills to `agents/<name>/skills/` as folders with `SKILL.md` files
- Only the skill name and description are loaded at startup (~100 tokens each)
- The agent reads the full SKILL.md on-demand when it decides to use a skill

## Next Steps

- Add skills: `smolclaw add-skill tars my-skill`
- Add more agents: `smolclaw add researcher --model claude-sonnet-4-6`
- Schedule jobs: `smolclaw cron add --agent tars --schedule "0 12 * * *" --prompt "lunch reminder"`
- Check health: `smolclaw doctor`
- View dashboard: open `http://localhost:7890` in a browser
