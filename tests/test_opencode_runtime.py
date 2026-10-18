"""OpenCode command and event contracts use OpenCode's own CLI dialect."""

import json


from electroboy.adapters.base import AgentInvocation
from electroboy.adapters.opencode_exec import OpenCodeExecRuntime
from electroboy.adapters.opencode_interactive import OpenCodeInteractiveRuntime
from electroboy.config import DEFAULT_CONFIG


def test_interactive_command_uses_prompt_and_private_server(tmp_path):
    runtime = OpenCodeInteractiveRuntime(
        DEFAULT_CONFIG.runtimes["opencode-interactive"], tmp_path
    )
    command = runtime._interactive_command(
        AgentInvocation(
            "design_author", "Write a design", provider_session_id="ses_design"
        )
    )
    assert command == [
        "opencode",
        str(tmp_path),
        "--standalone",
        "--session",
        "ses_design",
        "--prompt",
        "Write a design",
    ]


def test_text_parts_are_deduplicated_and_domain_json_is_retained(tmp_path):
    runtime = OpenCodeExecRuntime(DEFAULT_CONFIG.runtimes["opencode"], tmp_path)
    payload = {"cards": [{"id": "one"}]}
    event = {
        "type": "text",
        "sessionID": "ses_board",
        "part": {"id": "part_1", "text": json.dumps(payload)},
    }
    result = runtime._parse_stdout(json.dumps(event) + "\n" + json.dumps(event))
    assert result.ok
    assert result.structured_payload == payload
    assert json.loads(result.final_message) == payload
    assert result.provider_session_id == "ses_board"


def test_empty_or_error_stream_is_not_success(tmp_path):
    runtime = OpenCodeExecRuntime(DEFAULT_CONFIG.runtimes["opencode"], tmp_path)
    for stream in [
        "",
        "[]",
        '{"type":"step_start"}',
        '{"type":"error","error":{"message":"offline"}}',
    ]:
        result = runtime._parse_stdout(stream)
        assert not result.ok
        assert result.error


def test_schema_is_sent_in_prompt(tmp_path):
    runtime = OpenCodeExecRuntime(DEFAULT_CONFIG.runtimes["opencode"], tmp_path)
    schema = {"type": "object", "required": ["ok", "final_message", "issues"]}
    prompt = runtime._build_prompt(
        AgentInvocation("review", "Review", output_schema=schema)
    )
    assert json.dumps(schema) in prompt


def test_final_message_excludes_previous_tool_step_text(tmp_path):
    runtime = OpenCodeExecRuntime(DEFAULT_CONFIG.runtimes["opencode"], tmp_path)
    events = [
        {
            "type": "text",
            "part": {"messageID": "msg_1", "text": "I will review the code."},
        },
        {
            "type": "text",
            "part": {
                "messageID": "msg_2",
                "text": '{"ok":true,"final_message":"Done","issues":[]}',
            },
        },
    ]
    result = runtime._parse_stdout("\n".join(map(json.dumps, events)))
    assert result.ok and result.structured_output
    assert result.final_message == "Done"


def test_tutor_permissions_are_environment_only(monkeypatch):
    from electroboy.runtime import interactive_environment

    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", '{"model":"local/example"}')
    config = json.loads(
        interactive_environment("opencode", sandbox="read-only")[
            "OPENCODE_CONFIG_CONTENT"
        ]
    )
    assert config["model"] == "local/example"
    assert config["agent"]["electroboy-reader"]["permission"]["*"] == "deny"
    assert interactive_environment("codex", sandbox="read-only") == {}
