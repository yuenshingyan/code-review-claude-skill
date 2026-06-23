# Contributing

Thanks for your interest in improving this skill.

## Reporting bugs

Open an issue using the **Bug report** template. Include:

- What you asked Claude Code to review (mode, approximate diff size)
- What went wrong (broken rendering, missing sections, wrong classification)
- Your Claude Code version (`claude --version`)

## Suggesting features

Open an issue using the **Feature request** template. Describe the use case and any alternatives you considered.

## Making changes

The skill has two parts:

- **SKILL.md** — the specification that tells Claude how to gather diffs, classify changes, and produce JSON. Edit this to change the review workflow, schema, or content quality rules.
- **templates/code-review-template.html** — the self-contained HTML/CSS/JS that renders the JSON into an interactive review. Edit this to change the UI, keyboard shortcuts, or rendering behavior.

### Testing locally

1. Clone the repo into your skills directory:
   ```bash
   git clone https://github.com/yuenshingyan/code-review-claude-skill ~/.claude/skills/code-review
   ```
2. Make your changes.
3. Open any git project in Claude Code and run `/code-review`.
4. Open the generated `code-review.html` in a browser to verify.

### Pull requests

- Keep PRs focused — one change per PR.
- Test that the generated HTML still renders correctly after your changes.
- Update `CHANGELOG.md` with a summary under an "Unreleased" heading.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
