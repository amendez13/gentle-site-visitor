# AI Skills

This template ships a canonical `ai-skills/` source tree that renders to both Claude and Codex. The source files live in the repository once, and the deploy workflow writes the harness-specific outputs into `~/.claude/skills/` and `~/.codex/skills/`.

The shipped skill directories and manifests are project-specific. For example, `ai-skills/gentle-site-visitor-feature-delivery/skill.yaml` installs a skill named `gentle-site-visitor-feature-delivery`. This avoids different projects overwriting the same global `feature-delivery` skill in `~/.codex/skills` or `~/.claude/skills`.

## Why use a canonical source

Using one source of truth avoids drift between platform-specific skill directories:
- `instructions.md` is rendered into Claude's `skill.md` and Codex's `SKILL.md`
- the same optional `references/`, `scripts/`, and `assets/` directories are synced to both targets
- Codex-only interface metadata stays in `skill.yaml` instead of being hand-maintained in generated output

## Starter skills

The template ships:
- `gentle-site-visitor-example-skill`
  - Minimal copyable scaffold with a manifest, instructions, and a stub helper script.
- `gentle-site-visitor-feature-delivery`
  - Guides issue-driven delivery from branch creation through tests, PR, CI, review, merge, and cleanup.
- `gentle-site-visitor-feature-design`
  - Guides turning rough requests into implementation-ready GitHub issues and includes a helper for mockup screenshot uploads.
- `gentle-site-visitor-session-notes`
  - Documents the committed session-notes workflow used by this repository.

Use `gentle-site-visitor-example-skill` as the smallest starting point and the other shipped skills as fuller reference implementations.

## Canonical structure

Each skill lives under `ai-skills/<project-name>-<skill-name>/`:

```text
ai-skills/
  <project-name>-<skill-name>/
    skill.yaml
    instructions.md
    references/   # optional
    scripts/      # optional
    assets/       # optional
```

`skill.yaml` contains the shared manifest plus Codex UI metadata:

```yaml
name: gentle-site-visitor-example-skill
description: One-line project-specific description used by both Claude and Codex.
codex:
  interface:
    display_name: gentle-site-visitor Example Skill
    short_description: Short label shown in Codex UI
    default_prompt: Use $gentle-site-visitor-example-skill to do the thing.
```

## Deploy locally

Use the wrapper script:

```bash
./scripts/deploy_ai_skills.sh
```

Or run the playbook directly:

```bash
ansible-playbook infra/ai-skills/deploy_ai_skills.yml
```

The deploy workflow:
- discovers all `skill.yaml` manifests under `ai-skills/`
- renders Claude `skill.md` files into `~/.claude/skills/<name>/`
- renders Codex `SKILL.md` and `agents/openai.yaml` files into `~/.codex/skills/<name>/`
- syncs optional `references/`, `scripts/`, and `assets/` directories to both targets

## Add a new skill

1. Create `ai-skills/gentle-site-visitor-<name>/skill.yaml`.
2. Write the skill body in `ai-skills/gentle-site-visitor-<name>/instructions.md`.
3. Add optional `references/`, `scripts/`, or `assets/` directories when the skill needs them.
4. Run `./scripts/deploy_ai_skills.sh`.
5. Confirm the rendered files appear under both `~/.claude/skills/gentle-site-visitor-<name>/` and `~/.codex/skills/gentle-site-visitor-<name>/`.

Use `gentle-site-visitor-example-skill` for the minimal scaffold and `gentle-site-visitor-feature-delivery` / `gentle-site-visitor-feature-design` for fuller worked examples of naming, manifest structure, and guidance depth.

## Rendering differences

Claude and Codex share the same Markdown body, but the generated output differs slightly:
- Claude gets `skill.md`
- Codex gets `SKILL.md`
- Codex also gets `agents/openai.yaml` built from `skill.yaml`'s `codex.interface` block

The source directory remains canonical. Generated output should not be edited by hand.

## Troubleshooting

If a skill does not appear after deploy:
- verify `ansible-playbook` is installed and on your path
- confirm the skill has both `skill.yaml` and `instructions.md`
- make sure `skill.yaml` parses as valid YAML
- rerun `./scripts/deploy_ai_skills.sh` and inspect any Ansible errors

If Claude or Codex rejects a rendered skill:
- inspect the generated frontmatter under `~/.claude/skills/` or `~/.codex/skills/`
- check for malformed YAML or unsupported quoting in `skill.yaml`
- verify that `instructions.md` does not contain accidental template markers or broken fenced code blocks
