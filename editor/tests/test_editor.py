import json
import subprocess
import sys
from http.client import HTTPConnection
from pathlib import Path

import pytest
import yamlrocks
from rulegrid_editor import edit
from rulegrid_editor.server import Workspace

LEXICON = """# Words, by theme.
reminds: NO_DISALLOWED_CONTENT

entries:
  # --- Example terms
  - word: "first"
    meaning: "First term"  # keep
  - word: "second"
    meaning: "Second term"
tags: [a, b]
"""


def test_edit_keeps_comments_and_untouched_lines():
    entries = [{"word": "first", "meaning": "First example"}, {"word": "third", "meaning": "Third term"}]
    text = edit(LEXICON, ["entries"], entries)
    assert yamlrocks.loads(text)["entries"] == entries
    kept = ["# Words, by theme.", "reminds: NO_DISALLOWED_CONTENT", "", "  # --- Example terms", '  - word: "first"']
    assert all(line in text.splitlines() for line in kept)
    assert "# keep" in text

    appended = edit(LEXICON, ["entries"], [*yamlrocks.loads(LEXICON)["entries"], {"word": "x", "meaning": "y"}])
    assert appended.startswith(LEXICON.split("tags:")[0])
    assert edit(LEXICON, ["tags"], ["a", "b", "c"]).endswith('tags: ["a", "b", "c"]\n')
    assert '"second"' not in edit(LEXICON, ["entries", 1], None)


@pytest.mark.parametrize(
    ("example", "values", "tier"),
    [
        ("rbr", {"alert": "SELF_HARM_RISK", "theme": "GENERAL", "verb": "TRANSFORM"}, "alert"),
        ("three_laws", {"verb": "ORDER", "danger": "HUMAN"}, "first_law"),
    ],
)
def test_example_view_and_try(example, values, tier):
    root = Path(__file__).resolve().parents[2]
    workspace = Workspace(root / "examples" / example / "profiles" / "default", None)

    assert workspace.view({})["problems"] == []
    result = workspace.attempt({}, {"turn": "Hello", "turn_values": values})
    assert result["prescription"]["tier"] == tier


def test_server_requires_json_posts():
    profile = Path(__file__).resolve().parents[2] / "examples/three_laws/profiles/default"
    command = [sys.executable, "-c", "from rulegrid_editor import main; main()", str(profile), "--port", "0"]
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True) as server:
        try:
            assert server.stdout is not None
            port = int(server.stdout.readline().strip().rsplit(":", 1)[1])
            connection = HTTPConnection("127.0.0.1", port, timeout=5)
            try:
                connection.request("POST", "/api/save", "{}", {"Content-Type": "text/plain"})
                response = connection.getresponse()
                assert response.status == 415
                response.read()
                connection.request("POST", "/api/view", "{}", {"Content-Type": "application/json"})
                response = connection.getresponse()
                assert response.status == 200
                assert json.loads(response.read())["problems"] == []
            finally:
                connection.close()
        finally:
            server.terminate()
