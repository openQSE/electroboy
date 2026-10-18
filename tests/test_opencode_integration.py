"""Run the adapter through a real child process without a paid model call."""

import sys
from dataclasses import replace

from electroboy.adapters.base import AgentInvocation
from electroboy.adapters.opencode_exec import OpenCodeExecRuntime
from electroboy.adapters.opencode_interactive import OpenCodeInteractiveRuntime
from electroboy.config import DEFAULT_CONFIG


def executable(tmp_path, source):
    path = tmp_path / "opencode"
    path.write_text(f"#!{sys.executable}\n" + source)
    path.chmod(0o755)
    return str(path)


def test_exec_sends_stdin_schema_and_normalizes_result(tmp_path):
    command = executable(
        tmp_path,
        """import sys,json,os
assert sys.argv[1:5] == ['run','--standalone','--format','json']
prompt = sys.stdin.read()
assert 'required' in prompt and 'Review this code' in prompt
print(json.dumps({'type':'text','sessionID':'ses_review','part':{'text':json.dumps({'ok':True,'final_message':'Reviewed','issues':[]})}}))
""",
    )
    config = replace(DEFAULT_CONFIG.runtimes["opencode"], command=command)
    result = OpenCodeExecRuntime(config, tmp_path).invoke(
        AgentInvocation(
            "code_review",
            "Review this code",
            output_schema={"required": ["ok", "final_message", "issues"]},
        )
    )
    assert result.ok and result.structured_output
    assert result.final_message == "Reviewed"
    assert result.provider_session_id == "ses_review"


def test_interactive_initial_prompt_is_a_flag_and_session_identity_is_returned(
    tmp_path,
):
    command = executable(
        tmp_path,
        """import sys
assert '--standalone' in sys.argv
assert '--prompt' in sys.argv
assert sys.argv[sys.argv.index('--prompt')+1] == 'Help me'
assert sys.argv[sys.argv.index('--session')+1].startswith('ses_')
""",
    )
    config = replace(DEFAULT_CONFIG.runtimes["opencode-interactive"], command=command)
    result = OpenCodeInteractiveRuntime(config, tmp_path).invoke(
        AgentInvocation("design_author", "Help me")
    )
    assert result.ok and result.provider == "opencode"
    assert result.provider_session_id.startswith("ses_")
    assert not result.resumed_session


def test_nonzero_exit_preserves_provider_error(tmp_path):
    command = executable(
        tmp_path,
        'import sys\nprint("model unavailable", file=sys.stderr)\nsys.exit(2)\n',
    )
    config = replace(DEFAULT_CONFIG.runtimes["opencode"], command=command)
    result = OpenCodeExecRuntime(config, tmp_path).invoke(
        AgentInvocation("code_review", "Review")
    )
    assert not result.ok
    assert result.error == "model unavailable"
