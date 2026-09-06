export function cognitionResultLabel(event = {}) {
  if (!event.result_summary || !["background_cognition", "memory_shadow_extract"].includes(event.request_kind || "")) {
    return "";
  }
  const summary = event.result_summary;
  const memoryOperations = summary.memory_operations || 0;
  const applied = summary.memories_applied || 0;
  const deferred = summary.memories_deferred || 0;
  const threads = summary.thread_operations_applied || 0;
  const parts = [
    `${memoryOperations} memory ${memoryOperations === 1 ? "operation" : "operations"}`,
    `${applied} applied`
  ];
  if (deferred) parts.push(`${deferred} deferred`);
  parts.push(`${threads} thread ${threads === 1 ? "update" : "updates"}`);
  return parts.join(" · ");
}
