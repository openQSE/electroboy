# ElectroBoy Agent Guidelines

## Project Structure

ElectroBoy is a Python 3.10+ package using a `src/` layout:
- Core application code: `src/electroboy/`
- Browser service runtime assets: `src/electroboy/assets/service/`
- Reusable frontend modules: `src/electroboy/modules/`
- Workflow-specific code: `src/electroboy/workflows/` (software/, creative_writing/, code_learner/)
- Tests: `tests/`
- Distribution split-package metadata: `packages/`
- Operational docs and design artifacts: `docs/`

## Key Commands

- `python -m pip install -e .`: Install in editable mode
- `./electroboy --help`: Show CLI help
- `electroboy serve --port 9001`: Start browser service on development port
- `python -m pytest`: Run full test suite
- `python -m pytest tests/test_service.py -q`: Run main service regression tests

## Development Workflow

ElectroBoy enforces a disciplined AI-assisted development pipeline:
1. Define requirements with human operator and design author agent
2. Create and review detailed design
3. Approve implementation plan with small phases
4. Implement one phase at a time
5. Run code review, validation test review, validation, and documentation review
6. Preserve all review comments, decisions, commands, and artifacts

## Important Notes

- The tool enforces process discipline: no implementation before requirements, design, and implementation planning are approved
- Commands must be run from an activated project environment (source `<project>/.electroboy/bin/activate`)
- The workflow supports both feature runs (with feature-specific artifacts) and bug fixes
- Automated implementation uses phased commits with code review and validation gates
- Review agents require structured JSON output with `ok`, `final_message`, and `issues` fields
- Long-running non-interactive roles receive progress files and run with filesystem access to update those files

## Testing

- Tests use `pytest` and `unittest`-style test cases
- Tests are organized by module in the `tests/` directory
- For frontend asset changes, add static assertions in `tests/test_service.py`
- Run specific tests with `python -m pytest tests/<test_file>.py -q`

## Environment & Configuration

- The browser service reads environment variables:
  - `ELECTROBOY_SERVICE_ROOT`: GUI browse/base directory
  - `ELECTROBOY_SERVICE_STATE_ROOT`: workflow configuration, recent projects, service sessions, and transcripts
  - `ELECTROBOY_SERVICE_HOST`: bind address (default: `127.0.0.1`)
  - `ELECTROBOY_SERVICE_PORT`: bind port (default: `8765`)
  - `ELECTROBOY_SESSION_BACKEND`: agent session backend (default: `pty`, use `tmux` for long-running sessions)

## Runtime Adapters

The design supports configurable agent runtimes:
- Default: Codex (`codex_exec` adapter)
- Alternative: Generic CLI (`generic_cli` adapter)
- Interactive modes use `_interactive` suffix (e.g., `design_author_interactive`)

## Project Creation

Create a new project:
```bash
./electroboy new path/to/project
source path/to/project/.electroboy/bin/activate
```

For meta-projects (multiple related repositories):
```bash
electroboy meta init ~/ORNL/Quantum/openQSE
source ~/ORNL/Quantum/openQSE/.electroboy/bin/activate
electroboy add QFw qhw-characterization
electroboy start QFw
```

## Key Workflows

### Feature Development
```bash
electroboy feature start "Add dashboard export" --branch
electroboy requirements
electroboy requirements-approve
electroboy design
electroboy design-review
electroboy design-approve
electroboy implementation-plan
electroboy plan-approve
electroboy code
electroboy test-plan
electroboy test-plan-approve
electroboy validate
electroboy validation-approve
electroboy document
electroboy code-approve
```

### Bug Fixes
```bash
electroboy bug start https://tracker.example.com/issues/123 --branch
electroboy bug investigate
electroboy bug reproduce
electroboy bug fix
electroboy bug validate --command "python -m pytest tests/test_bug.py"
electroboy bug summary
```

## Workflow Commands

- `electroboy status`: Show current pipeline status
- `electroboy report summary`: Show summary report
- `electroboy report trace`: Show trace report
- `electroboy progress`: Show live agent progress
- `electroboy monitor`: Alias for `progress`
- `electroboy code-review`: Audit codebase or specific commits
- `electroboy validate`: Run validation tests
- `electroboy document`: Run documentation review
