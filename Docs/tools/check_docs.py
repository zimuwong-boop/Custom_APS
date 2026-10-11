"""Read-only documentation checks. This does not test a business application."""
from __future__ import annotations

import json
import re
from collections import Counter
from fractions import Fraction
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []
counts: Counter[str] = Counter()


def check(condition: bool, message: str, group: str) -> None:
    counts[group] += 1
    if not condition:
        errors.append(message)


markdown = sorted(ROOT.rglob("*.md"))
texts = {p: p.read_text(encoding="utf-8") for p in markdown}
req_text = texts[ROOT / "02_requirements.md"]
test_text = texts[ROOT / "09_Test_Acceptance.md"]
matrix = texts[ROOT / "10_Traceability.md"]
reqs = re.findall(r"^\| ((?:FR|NFR)-\d{3}) \|", req_text, re.M)
tests = re.findall(r"^\| (TC-\d{3}) \|", test_text, re.M)
all_ids = set(reqs + tests)
check(len(reqs) == len(set(reqs)), "Duplicate requirement ID", "identifiers")
check(len(tests) == len(set(tests)), "Duplicate test ID", "identifiers")
check(set(reqs) == {f"FR-{i:03}" for i in range(1, 28)} |
      {f"NFR-{i:03}" for i in range(1, 12)}, "Requirement inventory changed", "identifiers")
check(set(tests) == {f"TC-{i:03}" for i in range(1, 47)},
      "Test inventory changed", "identifiers")

matrix_rows = {}
for line in matrix.splitlines():
    match = re.match(r"\| ((?:FR|NFR)-\d{3}) \|", line)
    if match:
        key = match.group(1)
        check(key not in matrix_rows, f"Duplicate matrix row {key}", "traceability")
        matrix_rows[key] = line
check(set(matrix_rows) == set(reqs), "Matrix requirement coverage mismatch", "traceability")
for req in reqs:
    check(bool(re.search(r"TC-\d{3}", matrix_rows.get(req, ""))),
          f"No test linked to {req}", "traceability")
for test in tests:
    check(test in matrix, f"Test {test} not linked from requirements", "traceability")

for path, content in texts.items():
    relative = path.relative_to(ROOT)
    for identifier in re.findall(r"\b(?:FR|NFR|TC)-\d{3}\b", content):
        check(identifier in all_ids, f"{relative}: undefined {identifier}", "references")
    for target in re.findall(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)", content):
        if target.startswith(("https://", "http://", "mailto:", "#")):
            continue
        target_path = unquote(target.split("#", 1)[0])
        check((path.parent / target_path).exists(),
              f"{relative}: missing link {target}", "links")
    fence = None
    body: list[str] = []
    for line in content.splitlines():
        if line.startswith("```"):
            if fence is None:
                fence, body = line[3:].strip(), []
            else:
                if fence == "json":
                    try:
                        json.loads("\n".join(body))
                        check(True, "", "json_examples")
                    except json.JSONDecodeError as exc:
                        check(False, f"{relative}: JSON {exc}", "json_examples")
                if fence == "mermaid":
                    first = next((x.strip() for x in body if x.strip()), "")
                    check(first.split(" ")[0] in {
                        "flowchart", "classDiagram", "stateDiagram-v2",
                        "sequenceDiagram", "erDiagram"},
                        f"{relative}: unexpected Mermaid diagram type", "diagram_structure")
                fence, body = None, []
        elif fence is not None:
            body.append(line)
    check(fence is None, f"{relative}: unclosed code fence", "fences")

for path in sorted((ROOT / "diagrams").glob("*.puml")):
    source = path.read_text(encoding="utf-8")
    check(source.count("@startuml") == 1 and source.count("@enduml") == 1,
          f"{path.name}: invalid UML wrapper", "diagram_structure")

# Independent arithmetic examples, not copies of future production code.
f = Fraction
arithmetic = {
    "single child 36%": (f(60, 100) * f(60, 100), f(36, 100)),
    "multiple child 24%": (f(60, 100) * ((f(60, 100) + f(20, 100)) / 2), f(24, 100)),
    "own work 80%": (f(60, 100) + f(40, 100) * f(50, 100), f(80, 100)),
    "multilevel 36%": (f(60, 100) * (f(60, 100) * 1), f(36, 100)),
    "sales average 62%": ((f(36, 100) + f(60, 100) + f(90, 100)) / 3, f(62, 100)),
    "B1 allocation": (120 + 80, 200),
    "B2 allocation": (100 + 24, 124),
    "A2 input": (80 + 100, 180),
    "total allocation": (120 + 80 + 100 + 24, 324),
    "base quantity": (f(324 * 20, 100), f("64.8")),
    "cancel completed 60 of remaining 60": (min(f(1), f(60, 60)), f(1)),
    "cancel excess 80 of remaining 60": (min(f(1), f(80, 60)), f(1)),
    "cancel completed 30 of remaining 60": (f(30, 60), f(1, 2)),
    "repeat cancellation preserves exact 32": (f(32, 60) * 60 / 40, f(4, 5)),
    "parent cancellation credit exceeds base": (max(f(60, 100), f(60, 60)), f(1)),
}
for name, (actual, expected) in arithmetic.items():
    check(actual == expected, f"Arithmetic example: {name}", "arithmetic")


def ceil_step(value: Fraction, places: int) -> Fraction:
    scale = 10 ** places
    scaled = value * scale
    integer = (scaled.numerator + scaled.denominator - 1) // scaled.denominator
    return f(integer, scale)


check(ceil_step(f(1, 3), 6) == f("0.333334"), "Continuous rounding", "arithmetic")
check(ceil_step(f(1), 0) == 1, "Merged integer demand", "arithmetic")
check(2 * ceil_step(f(1, 2), 0) == 2, "Split integer demand", "arithmetic")
check(ceil_step(f(1, 3), 2) == f("0.34"), "Unit precision rounding", "arithmetic")

summary = {
    "status": "FAIL" if errors else "PASS",
    "markdown_documents": len(markdown),
    "requirements": len(reqs),
    "test_cases": len(tests),
    "checks": dict(counts),
    "total_checks": sum(counts.values()),
    "errors": errors,
    "scope": "Documentation structure and independent arithmetic only; no application tests or diagram rendering.",
}
print(json.dumps(summary, ensure_ascii=False, indent=2))
raise SystemExit(1 if errors else 0)
