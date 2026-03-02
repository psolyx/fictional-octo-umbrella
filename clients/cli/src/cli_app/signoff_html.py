from __future__ import annotations

import html


def html_escape(s: str) -> str:
    return html.escape(s, quote=True)


def render_page(title: str, body_html: str) -> str:
    safe_title = html_escape(title)
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '  <meta charset="utf-8">',
            '  <meta name="viewport" content="width=device-width, initial-scale=1">',
            f"  <title>{safe_title}</title>",
            "  <style>",
            "    :root { color-scheme: light dark; }",
            "    body { font-family: sans-serif; margin: 1rem auto; max-width: 80rem; padding: 0 1rem; line-height: 1.4; }",
            "    .skip-link { position: absolute; left: -9999px; top: 0; background: #fff; color: #000; padding: 0.5rem; border: 2px solid #000; }",
            "    .skip-link:focus { left: 0.5rem; z-index: 1000; }",
            "    a:focus-visible, button:focus-visible, [tabindex]:focus-visible { outline: 3px solid #005fcc; outline-offset: 2px; }",
            "    table { border-collapse: collapse; width: 100%; margin-top: 1rem; }",
            "    th, td { border: 1px solid #999; padding: 0.4rem; text-align: left; vertical-align: top; }",
            "    caption { text-align: left; font-weight: 700; margin-bottom: 0.4rem; }",
            "    .status { font-size: 1.15rem; font-weight: 700; }",
            "    .pass { color: #0f7a2f; }",
            "    .fail { color: #a10000; }",
            "    code { background: rgba(127, 127, 127, 0.15); padding: 0 0.2rem; border-radius: 0.2rem; }",
            "  </style>",
            "</head>",
            "<body>",
            '  <a class="skip-link" href="#content">Skip to content</a>',
            '  <main id="content">',
            body_html,
            "  </main>",
            "</body>",
            "</html>",
        ]
    )


def render_kv_list(items: list[tuple[str, str]]) -> str:
    lines = ["<dl>"]
    for key, value in items:
        lines.append(f"  <dt>{html_escape(key)}</dt>")
        lines.append(f"  <dd>{html_escape(value)}</dd>")
    lines.append("</dl>")
    return "\n".join(lines)


def render_table(caption: str, headers: list[str], rows: list[list[str]]) -> str:
    safe_caption = html_escape(caption)
    header_cells = "".join(f'<th scope="col">{html_escape(header)}</th>' for header in headers)
    table_lines = [
        "<table>",
        f"  <caption>{safe_caption}</caption>",
        f"  <thead><tr>{header_cells}</tr></thead>",
        "  <tbody>",
    ]
    for row in rows:
        row_cells = "".join(f"<td>{html_escape(cell)}</td>" for cell in row)
        table_lines.append(f"    <tr>{row_cells}</tr>")
    table_lines.extend(["  </tbody>", "</table>"])
    return "\n".join(table_lines)


def render_signoff_index(
    manifest: dict,
    artifacts: list[tuple[str, str]],
    result: str,
    notes: list[str],
) -> str:
    raw_steps = manifest.get("steps")
    steps = raw_steps if isinstance(raw_steps, list) else []
    step_rows: list[list[str]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        step_rows.append(
            [
                str(step.get("step_id", "")),
                str(step.get("label", "")),
                str(step.get("status", "")),
                str(step.get("duration_s", "")),
                str(step.get("exit_code", "")),
            ]
        )

    artifacts_lines = ["<ul>"]
    for href, label in artifacts:
        artifacts_lines.append(
            f'  <li><a href="{html_escape(href)}">{html_escape(label)}</a></li>'
        )
    artifacts_lines.append("</ul>")

    notes_lines = ["<ul>"]
    for note in notes:
        notes_lines.append(f"  <li><code>{html_escape(note)}</code></li>")
    notes_lines.append("</ul>")

    body = "\n".join(
        [
            "    <header>",
            "      <h1>Phase 5.2 Signoff Evidence</h1>",
            f'      <p class="status {"pass" if result == "PASS" else "fail"}" role="status">Result: {html_escape(result)}</p>',
            "    </header>",
            "    <section aria-labelledby=\"steps-heading\">",
            '      <h2 id="steps-heading">Step Summary</h2>',
            "      " + render_table(
                caption="Deterministic step outcomes from MANIFEST.json",
                headers=["step_id", "label", "status", "duration_s", "exit_code"],
                rows=step_rows,
            ).replace("\n", "\n      "),
            "    </section>",
            "    <section aria-labelledby=\"artifacts-heading\">",
            '      <h2 id="artifacts-heading">Artifacts</h2>',
            "      " + "\n      ".join(artifacts_lines),
            "    </section>",
            "    <section aria-labelledby=\"verify-heading\">",
            '      <h2 id="verify-heading">How to verify/compare</h2>',
            "      " + "\n      ".join(notes_lines),
            "    </section>",
        ]
    )
    return render_page("Phase 5.2 Signoff Evidence Index", body)


def render_signoff_compare(
    compare_manifest: dict,
    step_rows: list[list[str]],
    artifact_sections: dict[str, list[list[str]]],
) -> str:
    compare_result = str(compare_manifest.get("compare_result", "FAIL"))
    regression_count = str(compare_manifest.get("regression_count", "0"))
    status_class = "pass" if compare_result == "PASS" else "fail"

    def _section_table(title: str, caption: str, rows: list[list[str]]) -> str:
        return "\n".join(
            [
                f"      <h3>{html_escape(title)}</h3>",
                "      "
                + render_table(
                    caption=caption,
                    headers=["relpath", "A", "B"],
                    rows=rows,
                ).replace("\n", "\n      "),
            ]
        )

    body = "\n".join(
        [
            "    <header>",
            "      <h1>Phase 5.2 Signoff Compare</h1>",
            f'      <p class="status {status_class}" role="status">Result: {html_escape(compare_result)}</p>',
            f"      <p>regression_count={html_escape(regression_count)}</p>",
            "    </header>",
            "    <section aria-labelledby=\"step-delta-heading\">",
            '      <h2 id="step-delta-heading">Step delta</h2>',
            "      " + render_table(
                caption="Deterministic step-by-step comparison from MANIFEST.json",
                headers=[
                    "step_id",
                    "A status",
                    "A exit_code",
                    "A duration_s",
                    "B status",
                    "B exit_code",
                    "B duration_s",
                    "delta_s (B-A)",
                ],
                rows=step_rows,
            ).replace("\n", "\n      "),
            "    </section>",
            "    <section aria-labelledby=\"artifact-delta-heading\">",
            '      <h2 id="artifact-delta-heading">Artifact delta</h2>',
            _section_table("Changed", "Changed artifact digests (short)", artifact_sections.get("changed", [])),
            _section_table("Added", "Added artifacts", artifact_sections.get("added", [])),
            _section_table("Removed", "Removed artifacts", artifact_sections.get("removed", [])),
            "    </section>",
        ]
    )
    return render_page("Phase 5.2 Signoff Compare Report", body)


def render_signoff_catalog(catalog: dict) -> str:
    bundles_raw = catalog.get("bundles")
    compares_raw = catalog.get("compares")
    bundles = bundles_raw if isinstance(bundles_raw, list) else []
    compares = compares_raw if isinstance(compares_raw, list) else []

    def _table_with_html_cells(caption: str, headers: list[str], rows: list[list[str]]) -> str:
        header_cells = "".join(f'<th scope="col">{html_escape(header)}</th>' for header in headers)
        lines = ["<table>", f"  <caption>{html_escape(caption)}</caption>", f"  <thead><tr>{header_cells}</tr></thead>", "  <tbody>"]
        for row in rows:
            row_cells = "".join(f"<td>{cell}</td>" for cell in row)
            lines.append(f"    <tr>{row_cells}</tr>")
        lines.extend(["  </tbody>", "</table>"])
        return "\n".join(lines)

    bundle_rows: list[list[str]] = []
    for item in bundles:
        if not isinstance(item, dict):
            continue
        links = [
            f'<a href="{html_escape(str(item.get("index_href", "")))}">index.html</a>',
            f'<a href="{html_escape(str(item.get("sha256_href", "")))}">sha256.txt</a>',
            f'<a href="{html_escape(str(item.get("manifest_href", "")))}">MANIFEST.json</a>',
        ]
        if item.get("archive_href"):
            links.append(f'<a href="{html_escape(str(item.get("archive_href", "")))}">archive.tgz</a>')
        bundle_rows.append(
            [
                html_escape(str(item.get("created_utc", ""))),
                html_escape(str(item.get("result", ""))),
                html_escape(str(item.get("total_duration_s", ""))),
                "<br>".join(links),
            ]
        )

    compare_rows: list[list[str]] = []
    for item in compares:
        if not isinstance(item, dict):
            continue
        links = [
            f'<a href="{html_escape(str(item.get("compare_href", "")))}">compare.html</a>',
            f'<a href="{html_escape(str(item.get("manifest_href", "")))}">COMPARE_MANIFEST.json</a>',
        ]
        compare_rows.append(
            [
                html_escape(str(item.get("created_utc", ""))),
                html_escape(str(item.get("result", ""))),
                html_escape(str(item.get("regression_count", "0"))),
                "<br>".join(links),
            ]
        )

    body = "\n".join(
        [
            "    <header>",
            "      <h1>Phase 5.2 Signoff Catalog</h1>",
            f"      <p>evidence_root_basename={html_escape(str(catalog.get('evidence_root_basename', '')))}</p>",
            f"      <p>bundle_count={html_escape(str(catalog.get('bundle_count', 0)))} compare_count={html_escape(str(catalog.get('compare_count', 0)))}</p>",
            "    </header>",
            "    <section aria-labelledby=\"bundles-heading\">",
            '      <h2 id="bundles-heading">Bundles</h2>',
            "      "
            + _table_with_html_cells(
                caption="Bundles",
                headers=["created_utc", "result", "total_duration_s", "links"],
                rows=bundle_rows,
            ).replace("\n", "\n      "),
            "    </section>",
            "    <section aria-labelledby=\"compares-heading\">",
            '      <h2 id="compares-heading">Compares</h2>',
            "      "
            + _table_with_html_cells(
                caption="Compares",
                headers=["created_utc", "result", "regression_count", "links"],
                rows=compare_rows,
            ).replace("\n", "\n      "),
            "    </section>",
        ]
    )
    return render_page("Phase 5.2 Signoff Catalog", body)


def render_signoff_autopilot(
    *,
    manifest: dict,
    summary_lines: list[str],
    artifact_links: list[tuple[str, str]],
) -> str:
    result = "PASS" if bool(manifest.get("success")) else "FAIL"
    status_class = "pass" if result == "PASS" else "fail"
    summary_rows = [[line] for line in summary_lines]
    links_lines = ["<ul>"]
    for href, label in artifact_links:
        links_lines.append(
            f'  <li><a href="{html_escape(href)}">{html_escape(label)}</a></li>'
        )
    links_lines.append("</ul>")

    body = "\n".join(
        [
            "    <header>",
            "      <h1>Phase 5.2 Signoff Autopilot</h1>",
            f'      <p class="status {status_class}" role="status">Result: {html_escape(result)}</p>',
            "    </header>",
            "    <section aria-labelledby=\"summary-heading\">",
            '      <h2 id="summary-heading">Summary</h2>',
            "      "
            + render_table(
                caption="Deterministic AUTOPILOT_SUMMARY markers",
                headers=["line"],
                rows=summary_rows,
            ).replace("\n", "\n      "),
            "    </section>",
            "    <section aria-labelledby=\"artifacts-heading\">",
            '      <h2 id="artifacts-heading">Artifacts</h2>',
            "      " + "\n      ".join(links_lines),
            "    </section>",
            "    <section aria-labelledby=\"manifest-heading\">",
            '      <h2 id="manifest-heading">Manifest fields</h2>',
            "      "
            + render_kv_list(
                [
                    ("autopilot_version", str(manifest.get("autopilot_version", ""))),
                    ("bundle_dir_name", str(manifest.get("bundle_dir_name", ""))),
                    ("baseline_bundle_dir_name", str(manifest.get("baseline_bundle_dir_name", ""))),
                    ("verify_mode", str(manifest.get("verify_mode", ""))),
                    ("compare_mode", str(manifest.get("compare_mode", ""))),
                    ("compare_result", str(manifest.get("compare_result", ""))),
                ]
            ).replace("\n", "\n      "),
            "    </section>",
        ]
    )
    return render_page("Phase 5.2 Signoff Autopilot", body)
