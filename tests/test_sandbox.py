import os
import tempfile

from app.sandbox import run_in_sandbox


def test_successful_script_produces_declared_output():
    code = (
        "import os\n"
        "with open(os.path.join(os.environ['TASKGRAPH_WORKDIR'], 'output_result'), 'w') as f:\n"
        "    f.write('42')\n"
    )
    result = run_in_sandbox(code, input_files={}, expected_output_keys=["result"])
    assert result.success
    assert "result" in result.output_files
    with open(result.output_files["result"]) as f:
        assert f.read() == "42"


def test_missing_declared_output_is_a_failure():
    code = "pass\n"  # never writes output_result
    result = run_in_sandbox(code, input_files={}, expected_output_keys=["result"])
    assert not result.success
    assert "did not produce declared outputs" in result.error


def test_script_error_is_captured():
    code = "raise ValueError('boom')\n"
    result = run_in_sandbox(code, input_files={}, expected_output_keys=[])
    assert not result.success
    assert "exited with code" in result.error
    assert "boom" in result.stderr


def test_timeout_is_enforced():
    code = "import time\ntime.sleep(5)\n"
    result = run_in_sandbox(code, input_files={}, expected_output_keys=[], timeout_seconds=1)
    assert not result.success
    assert "timeout" in result.error


def test_input_file_is_visible_to_script():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("hello from input")
        input_path = f.name

    code = (
        "import os\n"
        "src = os.path.join(os.environ['TASKGRAPH_WORKDIR'], 'input_greeting')\n"
        "with open(src) as f: content = f.read()\n"
        "dst = os.path.join(os.environ['TASKGRAPH_WORKDIR'], 'output_echo')\n"
        "with open(dst, 'w') as f: f.write(content)\n"
    )
    result = run_in_sandbox(
        code,
        input_files={"greeting": input_path},
        expected_output_keys=["echo"],
    )
    assert result.success
    with open(result.output_files["echo"]) as f:
        assert f.read() == "hello from input"

    os.unlink(input_path)


def test_undeclared_input_is_not_visible():
    # Script tries to read something never copied in -- must fail cleanly,
    # not silently succeed by reaching outside the sandbox dir.
    code = (
        "import os\n"
        "path = os.path.join(os.environ['TASKGRAPH_WORKDIR'], 'input_secret')\n"
        "assert not os.path.exists(path), 'undeclared input should not exist'\n"
        "with open(os.path.join(os.environ['TASKGRAPH_WORKDIR'], 'output_ok'), 'w') as f:\n"
        "    f.write('ok')\n"
    )
    result = run_in_sandbox(code, input_files={}, expected_output_keys=["ok"])
    assert result.success
