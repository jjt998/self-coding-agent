from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_trace_events_from_jsonl(trace_path: Path) -> list[dict[str, Any]]:
    """读取 trace.jsonl，返回按写入顺序排列的事件列表。"""
    if not trace_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        events.append(json.loads(line))
    return events


def build_live_trace_snapshot(
    *,
    run_id: str,
    config_snapshot: dict[str, Any],
    trace_events: list[dict[str, Any]],
    report_text: str,
    final_diff_text: str,
    trace_path: str,
    report_path: str,
    diff_path: str,
    snapshot_json_path: str,
    snapshot_js_path: str,
) -> dict[str, Any]:
    """把事件流整理成实时对话 viewer 更容易消费的快照结构。"""
    event_type_counts: dict[str, int] = {}
    iteration_blocks: dict[int, dict[str, Any]] = {}
    global_events: list[dict[str, Any]] = []
    context_snapshot_payload: dict[str, Any] | None = None
    verification_payload: dict[str, Any] | None = None
    finalize_payload: dict[str, Any] | None = None
    run_finished_payload: dict[str, Any] | None = None
    last_timestamp = ""

    for event in trace_events:
        event_type = str(event.get("event_type", "unknown"))
        payload = event.get("payload", {})
        timestamp = str(event.get("timestamp", ""))
        last_timestamp = timestamp or last_timestamp
        event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1

        if event_type == "context_snapshot" and isinstance(payload, dict):
            context_snapshot_payload = payload
        elif event_type == "verification_result" and isinstance(payload, dict):
            verification_payload = payload
        elif event_type == "finalize_summary" and isinstance(payload, dict):
            finalize_payload = payload
        elif event_type == "run_finished" and isinstance(payload, dict):
            run_finished_payload = payload

        iteration = _extract_iteration_value(payload)
        if iteration is None:
            global_events.append(
                {
                    "event_type": event_type,
                    "timestamp": timestamp,
                    "payload": payload,
                }
            )
            continue

        block = iteration_blocks.setdefault(
            iteration,
            {
                "iteration": iteration,
                "timestamps": [],
                "model_request_prepared": None,
                "model_decision": None,
                "model_decision_failed": None,
                "tool_called": [],
                "tool_result": [],
                "reflect_feedback": None,
                "state_results": [],
                "event_count": 0,
            },
        )
        block["event_count"] += 1
        if timestamp:
            block["timestamps"].append(timestamp)

        if event_type == "model_request_prepared":
            block["model_request_prepared"] = payload
        elif event_type == "model_decision":
            block["model_decision"] = payload
        elif event_type == "model_decision_failed":
            block["model_decision_failed"] = payload
        elif event_type == "tool_called":
            block["tool_called"].append(payload)
        elif event_type == "tool_result":
            block["tool_result"].append(payload)
        elif event_type == "reflect_feedback":
            block["reflect_feedback"] = payload
        elif event_type == "state_result":
            block["state_results"].append(payload)

    iteration_items = [
        {
            **block,
            "started_at": block["timestamps"][0] if block["timestamps"] else "",
            "ended_at": block["timestamps"][-1] if block["timestamps"] else "",
        }
        for _, block in sorted(iteration_blocks.items())
    ]
    current_iteration = iteration_items[-1]["iteration"] if iteration_items else 0

    stop_reason = ((run_finished_payload or {}).get("stop_reason", {})) if isinstance(run_finished_payload, dict) else {}
    stop_reason_details = stop_reason.get("details", {}) if isinstance(stop_reason, dict) else {}
    verification_passed = bool((verification_payload or {}).get("passed"))
    token_usage = {}
    if isinstance(stop_reason_details, dict):
        token_usage = stop_reason_details.get("token_usage", {}) or {}

    return {
        "version": f"{len(trace_events)}:{last_timestamp}",
        "run_id": run_id,
        "task": config_snapshot.get("task", ""),
        "task_type": config_snapshot.get("task_type", ""),
        "trace_path": trace_path,
        "report_path": report_path,
        "diff_path": diff_path,
        "snapshot_json_path": snapshot_json_path,
        "snapshot_js_path": snapshot_js_path,
        "event_count": len(trace_events),
        "event_type_counts": event_type_counts,
        "current_iteration": current_iteration,
        "context_snapshot": context_snapshot_payload,
        "verification_result": verification_payload,
        "finalize_summary": finalize_payload,
        "run_finished": run_finished_payload,
        "verification_passed": verification_passed,
        "stop_reason": stop_reason,
        "token_usage": token_usage,
        "iterations": iteration_items,
        "global_events": global_events,
        "report_text": report_text,
        "final_diff_text": final_diff_text,
    }


def build_live_trace_view_html(*, run_id: str, snapshot_js_path: str) -> str:
    """构建轮询本地 JS 快照的实时对话 viewer。"""
    snapshot_js_literal = json.dumps(snapshot_js_path, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>实时任务过程 - {run_id}</title>
  <style>
    :root {{
      --bg: #f5efe5;
      --panel: #fffdf9;
      --ink: #1f1b16;
      --muted: #6f665d;
      --line: #d7cdbf;
      --harness: #1d4ed8;
      --harness-soft: #dbeafe;
      --model: #047857;
      --model-soft: #d1fae5;
      --warn: #92400e;
      --warn-soft: #fef3c7;
      --shadow: 0 14px 34px rgba(31, 27, 22, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      font-family: "Segoe UI", "PingFang SC", sans-serif;
      background:
        radial-gradient(circle at top left, #f6e8cf 0, transparent 22%),
        linear-gradient(180deg, #faf6ef 0%, var(--bg) 100%);
    }}
    .page {{
      max-width: 1600px;
      margin: 0 auto;
      padding: 18px;
      display: grid;
      gap: 16px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: var(--shadow);
    }}
    .hero {{
      padding: 20px 22px;
      display: grid;
      gap: 10px;
    }}
    h1, h2, h3, h4 {{
      margin: 0;
    }}
    .hero-meta, .status-bar {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .pill {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      background: #f7f1e8;
      border: 1px solid var(--line);
      font-size: 13px;
    }}
    .layout {{
      display: grid;
      grid-template-columns: 300px 1fr 360px;
      gap: 16px;
      align-items: start;
    }}
    .sidebar, .timeline, .detail {{
      display: grid;
      gap: 16px;
    }}
    .section {{
      padding: 16px;
      display: grid;
      gap: 12px;
    }}
    .stats {{
      display: grid;
      gap: 10px;
    }}
    .stat {{
      border: 1px solid var(--line);
      background: #faf6f0;
      border-radius: 14px;
      padding: 10px 12px;
      display: flex;
      justify-content: space-between;
      gap: 12px;
      font-size: 14px;
    }}
    .timeline-items {{
      display: grid;
      gap: 18px;
    }}
    .iteration {{
      border: 1px solid var(--line);
      border-radius: 18px;
      overflow: hidden;
      background: #fff;
    }}
    .iteration-header {{
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      background: #fcf8f1;
      display: flex;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .dialogue {{
      padding: 16px;
      display: grid;
      gap: 14px;
    }}
    .bubble {{
      display: grid;
      gap: 10px;
      max-width: min(88%, 980px);
      border-radius: 18px;
      border: 1px solid var(--line);
      padding: 14px;
      background: #fffdfb;
    }}
    .bubble.right {{
      justify-self: end;
      background: var(--harness-soft);
      border-color: #bfdbfe;
    }}
    .bubble.left {{
      justify-self: start;
      background: var(--model-soft);
      border-color: #a7f3d0;
    }}
    .bubble.warn {{
      background: var(--warn-soft);
      border-color: #fcd34d;
    }}
    .bubble-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }}
    .title {{
      font-weight: 700;
    }}
    .subtle {{
      color: var(--muted);
      font-size: 13px;
    }}
    .kv {{
      display: grid;
      gap: 8px;
    }}
    .kv-row {{
      display: grid;
      grid-template-columns: 120px 1fr;
      gap: 10px;
      align-items: start;
      font-size: 14px;
    }}
    .mono, pre {{
      font-family: "Cascadia Code", Consolas, monospace;
      font-size: 12px;
      line-height: 1.55;
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    details {{
      border: 1px solid rgba(0, 0, 0, 0.08);
      border-radius: 12px;
      background: rgba(255, 255, 255, 0.75);
      overflow: hidden;
    }}
    summary {{
      cursor: pointer;
      list-style: none;
      padding: 10px 12px;
      font-weight: 600;
      background: rgba(255, 255, 255, 0.55);
    }}
    summary::-webkit-details-marker {{ display: none; }}
    .details-body {{
      padding: 0 12px 12px;
    }}
    .chip-list {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .chip {{
      border-radius: 999px;
      padding: 5px 10px;
      background: rgba(255, 255, 255, 0.7);
      border: 1px solid rgba(0, 0, 0, 0.08);
      font-size: 12px;
    }}
    .actions {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    button {{
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 999px;
      padding: 8px 12px;
      font-weight: 600;
      cursor: pointer;
    }}
    button:hover {{
      border-color: var(--harness);
      color: var(--harness);
    }}
    .detail-pre {{
      min-height: 320px;
      max-height: 72vh;
      overflow: auto;
      background: #faf7f1;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px;
    }}
    .empty {{
      color: var(--muted);
      font-style: italic;
    }}
    .tool-list {{
      display: grid;
      gap: 10px;
    }}
    .tool-item {{
      border: 1px solid rgba(0, 0, 0, 0.08);
      border-radius: 12px;
      padding: 10px 12px;
      background: rgba(255, 255, 255, 0.7);
    }}
    .diff {{
      border: 1px solid var(--line);
      border-radius: 12px;
      overflow: hidden;
      background: #fff;
    }}
    .diff-line {{
      padding: 0 10px;
      white-space: pre-wrap;
      font-family: "Cascadia Code", Consolas, monospace;
      font-size: 12px;
      line-height: 1.55;
    }}
    .diff-line.add {{ background: #e8f7ec; color: #166534; }}
    .diff-line.del {{ background: #fde8e8; color: #991b1b; }}
    .diff-line.meta {{ background: #f1ece4; color: #6b5f52; }}
    @media (max-width: 1200px) {{
      .layout {{ grid-template-columns: 280px 1fr; }}
      .detail {{ grid-column: 1 / -1; }}
    }}
    @media (max-width: 860px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .bubble {{ max-width: 100%; }}
      .kv-row {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="panel hero">
      <h1>实时任务过程界面</h1>
      <div class="subtle">右侧显示 harness 发给模型的完整输入，左侧只显示结构化 model_decision。</div>
      <div class="hero-meta" id="heroMeta"></div>
      <div class="status-bar" id="statusBar"></div>
    </section>
    <div class="layout">
      <aside class="sidebar">
        <section class="panel section">
          <h2>运行概览</h2>
          <div class="stats" id="stats"></div>
        </section>
        <section class="panel section">
          <h2>最终 Diff</h2>
          <div id="diffContainer"></div>
        </section>
        <section class="panel section">
          <h2>全局事件</h2>
          <div id="globalEvents"></div>
        </section>
      </aside>
      <main class="timeline">
        <section class="panel section">
          <div class="actions">
            <button id="expandAll">展开全部工具详情</button>
            <button id="collapseAll">折叠全部工具详情</button>
          </div>
          <div class="timeline-items" id="timelineItems"></div>
        </section>
      </main>
      <aside class="detail">
        <section class="panel section">
          <h2>选中项 JSON</h2>
          <div class="subtle" id="detailTitle">点击任意请求卡片、决策卡片或工具结果后，在这里查看完整 JSON。</div>
          <pre class="detail-pre" id="detailJson">{{}}</pre>
        </section>
        <section class="panel section">
          <h2>报告快照</h2>
          <pre class="detail-pre" id="reportText"></pre>
        </section>
      </aside>
    </div>
  </div>
  <script>
    const snapshotScriptPath = {snapshot_js_literal};
    let latestVersion = "";
    let refreshTimer = null;

    function escapeHtml(value) {{
      return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }}

    function safeJson(value) {{
      return JSON.stringify(value ?? {{}}, null, 2);
    }}

    function setDetail(title, value) {{
      document.getElementById("detailTitle").textContent = title;
      document.getElementById("detailJson").textContent = safeJson(value);
    }}

    function parseUserPayload(requestPayload) {{
      const messages = Array.isArray(requestPayload?.messages) ? requestPayload.messages : [];
      const userMessage = [...messages].reverse().find((item) => item && item.role === "user");
      if (!userMessage || typeof userMessage.content !== "string") return null;
      try {{
        return JSON.parse(userMessage.content);
      }} catch (_error) {{
        return null;
      }}
    }}

    function renderHero(snapshot) {{
      document.getElementById("heroMeta").innerHTML = [
        ["Run", snapshot.run_id],
        ["task_type", snapshot.task_type || "unknown"],
        ["trace", snapshot.trace_path],
        ["live snapshot", snapshot.snapshot_json_path],
      ].map(([label, value]) => `<span class="pill"><strong>${{escapeHtml(label)}}</strong>${{escapeHtml(value)}}</span>`).join("");

      const stopReason = snapshot.stop_reason?.code || "running";
      const verificationText = snapshot.verification_passed ? "通过" : "未通过/未结束";
      const tokenUsage = snapshot.token_usage?.total_tokens ?? 0;
      document.getElementById("statusBar").innerHTML = [
        ["任务", snapshot.task || ""],
        ["当前轮次", snapshot.current_iteration || 0],
        ["事件数", snapshot.event_count || 0],
        ["stop reason", stopReason],
        ["最终验证", verificationText],
        ["total tokens", tokenUsage],
      ].map(([label, value]) => `<span class="pill">${{escapeHtml(label)}}：<strong>${{escapeHtml(value)}}</strong></span>`).join("");
    }}

    function renderStats(snapshot) {{
      const stopReason = snapshot.stop_reason || {{}};
      const rows = [
        ["任务类型", snapshot.task_type || "unknown"],
        ["当前轮次", snapshot.current_iteration || 0],
        ["轮次数", Array.isArray(snapshot.iterations) ? snapshot.iterations.length : 0],
        ["事件数", snapshot.event_count || 0],
        ["stop reason", stopReason.code || "running"],
        ["最终验证", snapshot.verification_passed ? "通过" : "未通过/未结束"],
        ["request_count", snapshot.token_usage?.request_count ?? 0],
        ["missing_usage_count", snapshot.token_usage?.missing_usage_count ?? 0],
      ];
      document.getElementById("stats").innerHTML = rows
        .map(([label, value]) => `<div class="stat"><span>${{escapeHtml(label)}}</span><strong>${{escapeHtml(value)}}</strong></div>`)
        .join("");
    }}

    function renderDiff(snapshot) {{
      const diffContainer = document.getElementById("diffContainer");
      const diffText = snapshot.final_diff_text || "";
      if (!diffText) {{
        diffContainer.innerHTML = '<div class="empty">当前还没有 final_diff.patch。</div>';
        return;
      }}
      const lines = diffText.split(/\\r?\\n/);
      diffContainer.innerHTML = `<div class="diff">${{lines.map((line) => {{
        let className = "";
        if (line.startsWith("+") && !line.startsWith("+++")) className = "add";
        else if (line.startsWith("-") && !line.startsWith("---")) className = "del";
        else if (line.startsWith("@@") || line.startsWith("---") || line.startsWith("+++")) className = "meta";
        return `<div class="diff-line ${{className}}">${{escapeHtml(line || " ")}}</div>`;
      }}).join("")}}</div>`;
    }}

    function renderGlobalEvents(snapshot) {{
      const root = document.getElementById("globalEvents");
      const globalEvents = Array.isArray(snapshot.global_events) ? snapshot.global_events : [];
      if (!globalEvents.length) {{
        root.innerHTML = '<div class="empty">暂无全局事件。</div>';
        return;
      }}
      root.innerHTML = globalEvents.slice(-8).map((event, index) => `
        <div class="tool-item" data-detail-kind="global" data-detail-index="${{index}}">
          <div><strong>${{escapeHtml(event.event_type)}}</strong></div>
          <div class="subtle">${{escapeHtml(event.timestamp || "")}}</div>
        </div>
      `).join("");
      globalEvents.slice(-8).forEach((event, index) => {{
        root.querySelector(`[data-detail-index="${{index}}"]`)?.addEventListener("click", () => {{
          setDetail(`全局事件：${{event.event_type}}`, event);
        }});
      }});
    }}

    function buildRequestOverview(userPayload, requestPayload) {{
      const contextSnapshot = userPayload?.context_snapshot || {{}};
      const repoContext = contextSnapshot.repo_context || {{}};
      const memoryContext = contextSnapshot.memory_context || {{}};
      const runtimeFeedback = userPayload?.runtime_feedback || {{}};
      const reflect = runtimeFeedback.previous_reflect || {{}};
      const stalePaths = Array.isArray(reflect.stale_file_paths) ? reflect.stale_file_paths : [];
      const previousDone = Array.isArray(runtimeFeedback.previous_donelist) ? runtimeFeedback.previous_donelist : [];
      return [
        ["model", requestPayload?.model || ""],
        ["selected_file_count", repoContext.selected_file_count ?? 0],
        ["runtime_rule_count", Array.isArray(memoryContext.runtime_rule_entries) ? memoryContext.runtime_rule_entries.length : 0],
        ["long_term_count", Array.isArray(memoryContext.long_term_entries) ? memoryContext.long_term_entries.length : 0],
        ["stale_file_paths", stalePaths.length ? stalePaths.join(", ") : "无"],
        ["previous_donelist_count", previousDone.length],
        ["previous_rationale", runtimeFeedback.previous_rationale || "无"],
      ];
    }}

    function renderRequestDetails(requestPayload, userPayload, iterationIndex) {{
      const overviewRows = buildRequestOverview(userPayload, requestPayload);
      const messages = requestPayload?.messages || [];
      const contextSnapshot = userPayload?.context_snapshot || {{}};
      const runtimeFeedback = userPayload?.runtime_feedback || {{}};
      const toolSchema = userPayload?.tool_schema || {{}};
      return `
        <div class="kv">
          ${{overviewRows.map(([label, value]) => `
            <div class="kv-row">
              <strong>${{escapeHtml(label)}}</strong>
              <div>${{escapeHtml(value)}}</div>
            </div>
          `).join("")}}
        </div>
        <details>
          <summary>messages</summary>
          <div class="details-body"><pre>${{escapeHtml(safeJson(messages))}}</pre></div>
        </details>
        <details>
          <summary>context_snapshot</summary>
          <div class="details-body"><pre>${{escapeHtml(safeJson(contextSnapshot))}}</pre></div>
        </details>
        <details>
          <summary>runtime_feedback</summary>
          <div class="details-body"><pre>${{escapeHtml(safeJson(runtimeFeedback))}}</pre></div>
        </details>
        <details>
          <summary>tool_schema</summary>
          <div class="details-body"><pre>${{escapeHtml(safeJson(toolSchema))}}</pre></div>
        </details>
        <details>
          <summary>raw request JSON</summary>
          <div class="details-body"><pre>${{escapeHtml(safeJson(requestPayload))}}</pre></div>
        </details>
        <div class="actions">
          <button data-detail-kind="request" data-detail-index="${{iterationIndex}}">查看请求 JSON</button>
        </div>
      `;
    }}

    function renderDecisionDetails(decisionPayload, iterationIndex) {{
      const summary = decisionPayload?.summary || "";
      const rationale = decisionPayload?.rationale || "";
      const plannedActions = Array.isArray(decisionPayload?.planned_actions) ? decisionPayload.planned_actions : [];
      const doneList = Array.isArray(decisionPayload?.donelist) ? decisionPayload.donelist : [];
      const toolCalls = Array.isArray(decisionPayload?.tool_calls) ? decisionPayload.tool_calls : [];
      const tokenUsage = decisionPayload?.token_usage || {{}};
      const notes = Array.isArray(decisionPayload?.normalization_notes) ? decisionPayload.normalization_notes : [];
      return `
        <div class="kv">
          <div class="kv-row"><strong>summary</strong><div>${{escapeHtml(summary)}}</div></div>
          <div class="kv-row"><strong>rationale</strong><div>${{escapeHtml(rationale)}}</div></div>
          <div class="kv-row"><strong>loop_end</strong><div>${{escapeHtml(decisionPayload?.loop_end ?? false)}}</div></div>
          <div class="kv-row"><strong>planned_actions</strong><div>${{escapeHtml(plannedActions.join(" | ") || "无")}}</div></div>
          <div class="kv-row"><strong>donelist</strong><div>${{escapeHtml(doneList.join(" | ") || "无")}}</div></div>
          <div class="kv-row"><strong>tool_calls</strong><div>${{escapeHtml(toolCalls.map((item) => item.tool_name).join(", ") || "无")}}</div></div>
          <div class="kv-row"><strong>token_usage</strong><div>${{escapeHtml(`prompt=${{tokenUsage.prompt_tokens ?? 0}}, completion=${{tokenUsage.completion_tokens ?? 0}}, total=${{tokenUsage.total_tokens ?? 0}}`)}}</div></div>
        </div>
        ${{
          notes.length
            ? `<details><summary>normalization_notes</summary><div class="details-body"><pre>${{escapeHtml(safeJson(notes))}}</pre></div></details>`
            : ""
        }}
        <details open>
          <summary>tool_calls</summary>
          <div class="details-body"><pre>${{escapeHtml(safeJson(toolCalls))}}</pre></div>
        </details>
        <div class="actions">
          <button data-detail-kind="decision" data-detail-index="${{iterationIndex}}">查看决策 JSON</button>
        </div>
      `;
    }}

    function renderToolSummary(iteration, iterationIndex) {{
      const toolCalled = Array.isArray(iteration.tool_called) ? iteration.tool_called : [];
      const toolResults = Array.isArray(iteration.tool_result) ? iteration.tool_result : [];
      const reflectFeedback = iteration.reflect_feedback;
      if (!toolCalled.length && !toolResults.length && !reflectFeedback) {{
        return '<div class="empty">本轮还没有工具执行结果。</div>';
      }}
      return `
        <details class="tool-details">
          <summary>工具执行摘要</summary>
          <div class="details-body tool-list">
            ${{
              toolCalled.map((item, toolIndex) => `
                <div class="tool-item">
                  <div><strong>tool_called</strong>：${{escapeHtml(item.tool_name || "unknown")}}</div>
                  <div class="subtle">${{escapeHtml(safeJson(item.tool_input || {{}}))}}</div>
                  <div class="actions">
                    <button data-detail-kind="tool_called" data-iteration-index="${{iterationIndex}}" data-tool-index="${{toolIndex}}">查看调用 JSON</button>
                  </div>
                </div>
              `).join("")
            }}
            ${{
              toolResults.map((item, toolIndex) => `
                <div class="tool-item">
                  <div><strong>tool_result</strong>：${{escapeHtml(item.tool_name || "unknown")}}</div>
                  <div class="subtle">${{escapeHtml(_buildToolResultHeadline(item.tool_output || {{}}))}}</div>
                  <div class="actions">
                    <button data-detail-kind="tool_result" data-iteration-index="${{iterationIndex}}" data-tool-index="${{toolIndex}}">查看结果 JSON</button>
                  </div>
                </div>
              `).join("")
            }}
            ${{
              reflectFeedback
                ? `
                  <div class="tool-item">
                    <div><strong>reflect_feedback</strong></div>
                    <div class="subtle">${{escapeHtml((reflectFeedback.signals || []).join(", ") || "无 signals")}}</div>
                    <div class="actions">
                      <button data-detail-kind="reflect_feedback" data-iteration-index="${{iterationIndex}}">查看 reflect JSON</button>
                    </div>
                  </div>
                `
                : ""
            }}
          </div>
        </details>
      `;
    }}

    function _buildToolResultHeadline(toolOutput) {{
      const parts = [];
      if (typeof toolOutput.ok !== "undefined") parts.push(`ok=${{toolOutput.ok}}`);
      if (toolOutput.path) parts.push(`path=${{toolOutput.path}}`);
      if (toolOutput.content_mode) parts.push(`content_mode=${{toolOutput.content_mode}}`);
      if (toolOutput.changed_file_count) parts.push(`changed_file_count=${{toolOutput.changed_file_count}}`);
      if (toolOutput.error) parts.push(`error=${{toolOutput.error}}`);
      return parts.join(" | ") || "查看完整 JSON";
    }}

    function renderTimeline(snapshot) {{
      const root = document.getElementById("timelineItems");
      const iterations = Array.isArray(snapshot.iterations) ? snapshot.iterations : [];
      if (!iterations.length) {{
        root.innerHTML = '<div class="empty">任务刚启动，等待第一轮模型决策写入 trace。</div>';
        return;
      }}
      root.innerHTML = iterations.map((iteration, iterationIndex) => {{
        const requestPayload = iteration.model_request_prepared?.request_payload || {{}};
        const userPayload = parseUserPayload(requestPayload);
        const decisionPayload = iteration.model_decision;
        const failurePayload = iteration.model_decision_failed;
        const leftClass = failurePayload ? "bubble left warn" : "bubble left";
        const leftTitle = failurePayload ? "Model Decision Failed" : "Model Decision";
        const leftBody = failurePayload
          ? `
            <div class="kv">
              <div class="kv-row"><strong>error_type</strong><div>${{escapeHtml(failurePayload.error_type || "unknown")}}</div></div>
              <div class="kv-row"><strong>error_message</strong><div>${{escapeHtml(failurePayload.error_message || "")}}</div></div>
            </div>
            <div class="actions">
              <button data-detail-kind="decision_failed" data-detail-index="${{iterationIndex}}">查看失败 JSON</button>
            </div>
          `
          : renderDecisionDetails(decisionPayload || {{}}, iterationIndex);
        return `
          <section class="iteration">
            <div class="iteration-header">
              <div><strong>第 ${{iteration.iteration}} 轮</strong></div>
              <div class="subtle">${{escapeHtml(iteration.started_at || "")}} -> ${{escapeHtml(iteration.ended_at || "")}}</div>
            </div>
            <div class="dialogue">
              <article class="bubble right">
                <div class="bubble-head">
                  <div class="title">Harness -> Model</div>
                  <div class="subtle">完整请求快照</div>
                </div>
                ${{
                  iteration.model_request_prepared
                    ? renderRequestDetails(requestPayload, userPayload, iterationIndex)
                    : '<div class="empty">本轮还没有 request 快照。</div>'
                }}
              </article>
              <article class="${{leftClass}}">
                <div class="bubble-head">
                  <div class="title">${{leftTitle}}</div>
                  <div class="subtle">只显示解析后的结构化结果</div>
                </div>
                ${{leftBody}}
              </article>
              ${{renderToolSummary(iteration, iterationIndex)}}
            </div>
          </section>
        `;
      }}).join("");

      iterations.forEach((iteration, iterationIndex) => {{
        root.querySelector(`[data-detail-kind="request"][data-detail-index="${{iterationIndex}}"]`)?.addEventListener("click", () => {{
          setDetail(`第 ${{iteration.iteration}} 轮请求`, iteration.model_request_prepared?.request_payload || {{}});
        }});
        root.querySelector(`[data-detail-kind="decision"][data-detail-index="${{iterationIndex}}"]`)?.addEventListener("click", () => {{
          setDetail(`第 ${{iteration.iteration}} 轮 model_decision`, iteration.model_decision || {{}});
        }});
        root.querySelector(`[data-detail-kind="decision_failed"][data-detail-index="${{iterationIndex}}"]`)?.addEventListener("click", () => {{
          setDetail(`第 ${{iteration.iteration}} 轮 model_decision_failed`, iteration.model_decision_failed || {{}});
        }});
        (iteration.tool_called || []).forEach((toolItem, toolIndex) => {{
          root
            .querySelector(`[data-detail-kind="tool_called"][data-iteration-index="${{iterationIndex}}"][data-tool-index="${{toolIndex}}"]`)
            ?.addEventListener("click", () => {{
              setDetail(`第 ${{iteration.iteration}} 轮 tool_called`, toolItem);
            }});
        }});
        (iteration.tool_result || []).forEach((toolItem, toolIndex) => {{
          root
            .querySelector(`[data-detail-kind="tool_result"][data-iteration-index="${{iterationIndex}}"][data-tool-index="${{toolIndex}}"]`)
            ?.addEventListener("click", () => {{
              setDetail(`第 ${{iteration.iteration}} 轮 tool_result`, toolItem);
            }});
        }});
        root
          .querySelector(`[data-detail-kind="reflect_feedback"][data-iteration-index="${{iterationIndex}}"]`)
          ?.addEventListener("click", () => {{
            setDetail(`第 ${{iteration.iteration}} 轮 reflect_feedback`, iteration.reflect_feedback || {{}});
          }});
      }});
    }}

    function render(snapshot) {{
      renderHero(snapshot);
      renderStats(snapshot);
      renderDiff(snapshot);
      renderGlobalEvents(snapshot);
      renderTimeline(snapshot);
      document.getElementById("reportText").textContent = snapshot.report_text || "";
      if (!latestVersion) {{
        setDetail("实时快照总览", snapshot);
      }}
    }}

    function reloadSnapshot() {{
      const cacheBust = `ts=${{Date.now()}}`;
      const script = document.createElement("script");
      script.src = `${{snapshotScriptPath}}?${{cacheBust}}`;
      script.onload = () => {{
        const snapshot = window.__LIVE_TRACE_SNAPSHOT__ || null;
        if (!snapshot || !snapshot.version) return;
        if (snapshot.version === latestVersion) return;
        latestVersion = snapshot.version;
        render(snapshot);
      }};
      script.onerror = () => {{
        // run 刚启动且快照尚未写出时，不把页面打成错误态，下一轮轮询继续尝试。
      }};
      document.body.appendChild(script);
      script.remove();
    }}

    document.getElementById("expandAll").addEventListener("click", () => {{
      document.querySelectorAll(".tool-details").forEach((item) => item.open = true);
    }});
    document.getElementById("collapseAll").addEventListener("click", () => {{
      document.querySelectorAll(".tool-details").forEach((item) => item.open = false);
    }});

    reloadSnapshot();
    refreshTimer = window.setInterval(reloadSnapshot, 1500);
  </script>
</body>
</html>
"""


def _extract_iteration_value(payload: Any) -> int | None:
    """从 payload 中提取统一的 iteration 值。"""
    if not isinstance(payload, dict):
        return None
    for field_name in ["iteration", "current_iteration"]:
        raw_value = payload.get(field_name)
        if isinstance(raw_value, int):
            return raw_value if raw_value > 0 else None
        if isinstance(raw_value, str) and raw_value.strip().isdigit():
            normalized_value = int(raw_value.strip())
            return normalized_value if normalized_value > 0 else None
    return None
