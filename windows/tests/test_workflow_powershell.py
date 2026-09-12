"""Parse workflow PowerShell with the real parser, including Windows' default shell."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/windows-build-scripts.yml"


def powershell_steps():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for job_id, job in workflow["jobs"].items():
        default = job.get("defaults", workflow.get("defaults", {})).get("run", {}).get("shell")
        default = default or ("pwsh" if "windows" in str(job.get("runs-on", "")) else "bash")
        for index, step in enumerate(job["steps"]):
            if "run" in step and step.get("shell", default).split()[0] in ("pwsh", "powershell"):
                # Actions resolves expressions before writing the temporary script. Use a harmless
                # literal for syntax validation; this does not execute any workflow commands.
                script = re.sub(r"\$\{\{.*?\}\}", "ci_value", step["run"], flags=re.DOTALL)
                yield f"{job_id}/{step.get('name', index)}", script


@pytest.mark.parametrize("name,script", [pytest.param(name, script, id=name) for name, script in powershell_steps()])
def test_workflow_powershell_parses(name, script, tmp_path):
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if not pwsh:
        pytest.skip("PowerShell parser unavailable; required by the validate CI job")
    source = tmp_path / "step.ps1"
    source.write_text(script, encoding="utf-8")
    parser = tmp_path / "parse.ps1"
    parser.write_text(
        "param([string]$Source)\n"
        "$tokens=$null; $errors=$null\n"
        "[System.Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors) | Out-Null\n"
        "if ($errors) { $errors | ForEach-Object { Write-Output $_ }; exit 1 }\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [pwsh, "-NoProfile", "-File", str(parser), str(source)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"{name}:\n{result.stdout}\n{result.stderr}"
