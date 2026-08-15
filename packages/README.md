# Production Distributions

The root `electroboy` project remains the standard all-in-one developer and
user installation. Production builds can instead build and install selected
distributions from this directory:

- `electroboy-core` provides the CLI, service runtime, registries, and browser
  shell.
- `electroboy-modules` provides the reusable built-in capability modules.
- `electroboy-workflow-software` provides the software-engineering controller
  and frontend bundle.
- `electroboy-workflow-creative-writing` provides the creative-writing
  controller and frontend bundle.

Each optional distribution registers its contributions with Python entry
points. The core imports a workflow or module only after discovering its entry
point. A selected customer build can therefore omit either workflow wheel.

Build wheels from the repository root with:

```bash
python -m pip wheel --no-deps --wheel-dir dist packages/electroboy-core
python -m pip wheel --no-deps --wheel-dir dist packages/electroboy-modules
python -m pip wheel --no-deps --wheel-dir dist \
  packages/electroboy-workflow-software
python -m pip wheel --no-deps --wheel-dir dist \
  packages/electroboy-workflow-creative-writing
```
