# Contributing to DIMO

First off, thank you for considering contributing to DIMO! It's people like you that make open-source such a great community.

## Where do I go from here?

If you've noticed a bug or have a feature request, make sure to check our [Issues](../../issues) to see if someone else has already created a ticket. If not, go ahead and [make one](../../issues/new).

## Fork & create a branch

If this is something you think you can fix, then [fork DIMO](https://docs.github.com/en/get-started/quickstart/fork-a-repo) and create a branch with a descriptive name.

## Adding a New Tool

DIMO is highly extensible. To add a new tool to the ecosystem:
1. Create your implementation inside the `app/tools/native/` or `app/browser/` folder.
2. Register your tool by creating an entry in `TOOL_CATALOG` within `app/tools/registry.py`.
3. Provide a clear, detailed `description` and OpenAPI-style `parameters` block so the Planner LLM knows how to use it.
4. Ensure you write isolated tests for your new tool.

## Testing

Always test your changes to ensure they don't break existing functionality. We have two main testing strategies:
- **Isolated Tests:** Check the individual capabilities by running scripts like `python testing/test_vision.py` or `python testing/test_ollama.py`.
- **E2E Testing:** Run `python main.py` and test end-to-end functionality conversationally.

## Pull Request Guidelines

- Ensure your branch is updated with the `main` branch.
- Resolve any merge conflicts.
- Include a descriptive PR title and a comprehensive description of the changes you've made.
- We will review your PR and merge it once it has been approved.

Thank you for contributing!
