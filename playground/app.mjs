const $ = id => document.getElementById(id);
const input = $("input");
const MAX_BYTES = 1024 * 1024;
const DECISIONS = { REJECT: "reject", HUMAN_REVIEW_REQUIRED: "human", PILOT_ELIGIBLE: "pilot" };
const STATUS_LABEL = { blocker: "Blocker", review: "Review", pass: "Pass", note: "Diagnostic" };
const STATUS_ORDER = { blocker: 0, review: 1, note: 2, pass: 3 };

let worker, timer, ready = false, busy = false, samples = null;
let scored = null, checkedKey = "", pendingKey = "", requestId = 0;
let filter = "open", modified = false, expanded = false, reviewName = "";

const settings = () => ({ case: $("case").value, aliases: $("aliases").checked ? "on" : "off" });
// The case and the alias setting are part of what was scored, so either change makes a result stale.
const reviewKey = () => `${$("case").value}\n${settings().aliases}\n${input.value}`;
const isCurrent = () => Boolean(scored) && checkedKey === reviewKey();

function showError(id, message = "") {
  $(id).textContent = message;
  $(id).hidden = !message;
}

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

// Mirrors the first checks of the review schema so obvious mistakes are named before Python runs.
function parseReview(text) {
  if (new TextEncoder().encode(text).length > MAX_BYTES) {
    throw new Error("This playground accepts reviews up to 1 MB. Use the CLI for larger files.");
  }
  let review;
  try { review = JSON.parse(text); }
  catch { throw new Error("The review is not valid JSON. Check quotation marks, commas and brackets."); }
  if (!review || typeof review !== "object" || Array.isArray(review)) {
    throw new Error("The review must be a JSON object. Load an example to see the structure.");
  }
  for (const key of ["clauses", "risk_flags", "citations"]) {
    if (!Array.isArray(review[key])) throw new Error(`Add a "${key}" list. Use an empty list if the review has none.`);
  }
  return review;
}

function syncDraft() {
  const size = new TextEncoder().encode(input.value).length;
  $("size").textContent = `${(size / 1024).toFixed(1)} KB`;
  try {
    const review = parseReview(input.value);
    $("shape").textContent = `${review.clauses.length} clauses · ${review.risk_flags.length} risk flags · ${review.citations.length} citations`;
  } catch { $("shape").textContent = input.value.trim() ? "Review structure needs attention" : "Paste or load a review"; }
  const current = isCurrent();
  $("stale").hidden = !scored || current;
  $("export-json").disabled = !current || busy;
  $("export-md").disabled = !current || busy;
  $("run").disabled = !ready || busy;
  $("run").firstChild.textContent = busy ? "Scoring… " : "Score review ";
  $("result-state").textContent = busy ? "Scoring review" : scored ? (current ? "Score complete" : "Review changed") : "Awaiting score";
  document.querySelector(".results-panel").setAttribute("aria-busy", String(busy));
  document.querySelectorAll(".locate-button").forEach(button => { button.disabled = !current; });
}

input.addEventListener("input", () => {
  modified = true;
  showError("input-error");
  showError("run-error");
  input.removeAttribute("aria-invalid");
  syncDraft();
});

function replaceReview(text, name = "") {
  if (input.value && modified && !window.confirm("Replace this edited review? Save a copy first if you need to keep it.")) return false;
  input.value = text;
  reviewName = name;
  modified = false;
  showError("input-error");
  showError("sample-error");
  showError("run-error");
  input.removeAttribute("aria-invalid");
  syncDraft();
  return true;
}

function renderContract(span = null) {
  const info = samples?.cases[$("case").value];
  const pre = $("contract");
  if (!info) { pre.textContent = ""; return null; }
  if (!span) { pre.textContent = info.contract; return null; }
  const mark = node("mark", span.grounded ? "grounded" : "", info.contract.slice(span.start, span.end));
  pre.replaceChildren(info.contract.slice(0, span.start), mark, info.contract.slice(span.end));
  return mark;
}

function showCase() {
  const key = $("case").value;
  $("case-badge").textContent = key.toUpperCase();
  const info = samples?.cases[key];
  if (!info) return;
  const context = info.context;
  $("context").textContent = context
    ? `Answer set: ${info.clause_count} clauses, ${info.risk_count} risks, judged for the ${context.party}. Governing law: ${context.governing_law}. Risk appetite: ${context.risk_appetite}.`
    : `Answer set: ${info.clause_count} clauses, ${info.risk_count} risks.`;
  $("contract-title").textContent = info.title;
  renderContract();
}

function loadExample() {
  const review = samples?.cases[$("case").value].reviews[$("example").value];
  if (review) replaceReview(JSON.stringify(review, null, 2));
}

async function loadSamples() {
  try {
    const response = await fetch("samples.json");
    if (!response.ok) throw new Error();
    samples = await response.json();
    showCase();
    if (!input.value) loadExample();
    showError("sample-error");
  } catch {
    samples = null;
    $("context").textContent = "";
    showError("sample-error", "Examples could not load. Press Load to retry, or import or paste a review.");
  }
  $("load-example").disabled = false;
}

$("load-example").onclick = async () => {
  if (!samples) await loadSamples();
  loadExample();
};
$("case").onchange = () => {
  showCase();
  // An untouched example follows the contract; an edited review stays and is marked stale.
  if (!modified && samples) loadExample();
  syncDraft();
};
$("aliases").onchange = syncDraft;
$("import").onclick = () => $("file").click();
$("file").onchange = async event => {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file) return;
  const before = input.value;
  try {
    if (file.size > MAX_BYTES) throw new Error("The file exceeds the 1 MB playground limit. Use the CLI for larger files.");
    // file.text() would silently swap invalid bytes for U+FFFD, which would then fail grounding for the wrong reason.
    let text;
    try { text = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer()); }
    catch { throw new Error("The file is not valid UTF-8. Save it as UTF-8 and import it again."); }
    if (input.value !== before) throw new Error("The review changed while the file was opening. Import the file again when you are ready.");
    replaceReview(text, file.name);
  } catch (error) { showError("input-error", error.message || "The file could not be read. Try a UTF-8 JSON file."); }
};

$("format").onclick = () => {
  try {
    const formatted = JSON.stringify(JSON.parse(input.value), null, 2);
    if (formatted !== input.value) {
      input.value = formatted;
      modified = true;
    }
    showError("input-error");
    input.removeAttribute("aria-invalid");
    syncDraft();
  } catch { showError("input-error", "The review is not valid JSON. Check quotation marks, commas and brackets."); }
};

function runtimeFailed(message) {
  clearTimeout(timer);
  worker?.terminate();
  ready = false;
  busy = false;
  $("status").textContent = message;
  $("status-dot").className = "status-dot error";
  $("retry").hidden = false;
  syncDraft();
}

function startRuntime() {
  worker?.terminate();
  clearTimeout(timer);
  ready = false;
  busy = false;
  $("retry").hidden = true;
  $("status-dot").className = "status-dot";
  $("status").textContent = "Loading Python runtime…";
  syncDraft();
  try {
    const instance = new Worker(new URL("runtime.mjs", import.meta.url), { type: "module" });
    worker = instance;
    timer = setTimeout(() => runtimeFailed("Loading timed out. Check your connection and retry; your review is still here."), 90000);
    instance.onerror = event => {
      event.preventDefault();
      if (worker === instance) runtimeFailed("The scorer stopped. Retry to reload it; your review is still here.");
    };
    instance.onmessage = ({ data }) => {
      if (worker !== instance) return;
      if (data.type === "progress") $("status").textContent = data.text;
      if (data.type === "ready") {
        clearTimeout(timer);
        ready = true;
        $("status").textContent = "Ready. Scoring runs locally in your browser.";
        $("status-dot").className = "status-dot ready";
        syncDraft();
      }
      if (data.type === "error") {
        if (data.id === undefined) runtimeFailed(data.text);
        else if (data.id === requestId) {
          clearTimeout(timer);
          busy = false;
          showError("run-error", data.text);
          syncDraft();
        }
      }
      if (data.type === "result" && data.id === requestId) {
        clearTimeout(timer);
        busy = false;
        scored = data;
        checkedKey = pendingKey;
        renderResult();
        syncDraft();
      }
    };
    const wheelName = document.querySelector("script[data-wheel]").dataset.wheel;
    instance.postMessage({ type: "init", wheelUrl: new URL(wheelName, location.href).href });
  } catch { runtimeFailed("This browser could not start the scorer. Enable web workers and retry, or use the CLI."); }
}

function runScore() {
  if (!ready || busy) return;
  showError("input-error");
  showError("run-error");
  try { parseReview(input.value); }
  catch (error) {
    showError("input-error", error.message);
    input.setAttribute("aria-invalid", "true");
    input.focus();
    return;
  }
  input.removeAttribute("aria-invalid");
  busy = true;
  pendingKey = reviewKey();
  requestId += 1;
  syncDraft();
  timer = setTimeout(() => runtimeFailed("The score timed out. Retry the scorer and score again."), 30000);
  const { case: caseId, aliases } = settings();
  worker.postMessage({ type: "score", id: requestId, text: input.value, case: caseId, aliases, name: reviewName });
}
$("run").onclick = runScore;
$("retry").onclick = startRuntime;
input.addEventListener("keydown", event => {
  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) { event.preventDefault(); runScore(); }
});

const ratio = value => value.toFixed(2);

function scoreRows(s) {
  return [
    ["Clause precision", ratio(s.clause_precision), "predicted clause types that were expected"],
    ["Clause recall", ratio(s.clause_recall), "expected clause types that were found"],
    ["Clause F1", ratio(s.clause_f1), "harmonic mean of precision and recall"],
    ["Risk precision", ratio(s.risk_precision), "flagged clauses that the answer set treats as risks"],
    ["Risk recall", ratio(s.risk_recall), "answer-set risks the review flagged"],
    ["Risk F1", ratio(s.risk_f1), "harmonic mean of risk precision and recall"],
    ["Severity accuracy", ratio(s.risk_severity_accuracy), "correct severity among jointly identified risks"],
    ["Risk false positives", String(s.risk_false_positives.length), "clauses flagged that the answer set does not treat as risks"],
    ["Risk missed", String(s.risk_missed.length), "answer-set risks the review did not flag"],
    ["Duplicate / conflicting flags", `${s.risk_duplicate_flags.length} / ${s.risk_conflicting_flags.length}`, "predictions collapsing onto one clause"],
    ["Span coverage", ratio(s.span_coverage), "answer-set clauses with a grounded citation inside them"],
    ["Citation grounding", ratio(s.citation_grounding), `${s.citation_grounded}/${s.citation_total} quotes matched as an exact span of the normalised source`],
    ["Hallucination count", String(s.hallucination_count), "cited quotes not grounded in the source"],
    ["Risk-flag accuracy (legacy)", ratio(s.risk_flag_accuracy), "blind to false positives; excluded from release decisions"],
  ];
}

function renderResult() {
  const result = scored.result;
  const s = result.scores;
  const info = samples?.cases[result.case];
  $("empty").hidden = true;
  $("results").hidden = false;
  $("report-title").textContent = info?.title ?? result.case.toUpperCase();
  $("report-meta").textContent = `Policy ${result.policy} · aliases ${result.alias_mode === "on" ? "applied" : "not applied"} · result ${result.result_sha256.slice(0, 12)}`;
  $("decision").className = `decision ${DECISIONS[result.decision]}`;
  $("decision-value").textContent = result.decision;
  $("decision-note").textContent = scored.note;
  const counts = [["count-blockers", result.blockers.length], ["count-review", result.review_items.length]];
  for (const [id, count] of counts) {
    $(id).textContent = count;
    $(id).classList.toggle("zero", count === 0);
  }
  $("clause-f1").textContent = ratio(s.clause_f1);
  $("grounding").replaceChildren(String(s.citation_grounded), node("small", "", `/${s.citation_total}`));
  $("grounding").classList.toggle("zero", s.citation_total > 0 && s.citation_grounded === s.citation_total);
  $("score-table").replaceChildren(...scoreRows(s).map(cells => {
    const row = node("tr");
    cells.forEach(cell => row.append(node("td", "", cell)));
    return row;
  }));
  const name = result.inputs.review_output.path;
  $("export-hint").replaceChildren("Take the result with you", node("small", "", `Matches the CLI on the saved review: contract-eval score ${name} --case ${result.case}${result.alias_mode === "off" ? " --aliases off" : ""}`));
  renderContract();
  renderFindings();
}

function selectFindings(findings) {
  const query = $("search").value.trim().toLowerCase();
  return findings
    .filter(f => (filter === "all" || (filter === "open" ? f.status === "blocker" || f.status === "review" : f.category === filter))
      && [f.label, f.meta, f.key, ...f.detail].join(" ").toLowerCase().includes(query))
    .sort((a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status]);
}

function locate(finding) {
  if (!isCurrent() || !finding.span) return;
  $("contract-details").open = true;
  const mark = renderContract({ start: finding.span[0], end: finding.span[1], grounded: finding.category === "citation" });
  mark?.scrollIntoView({ block: "center", behavior: "instant" });
}

function renderFindings() {
  if (!scored) return;
  const all = scored.findings;
  const findings = selectFindings(all);
  const container = $("findings");
  container.replaceChildren();
  $("visible-count").textContent = `${findings.length} of ${all.length} findings · blockers first`;
  if (!findings.length) {
    container.append(node("p", "no-findings", filter === "open" && !$("search").value
      ? "No open items. Every requirement of the release policy is met."
      : "No findings match this view. Try another filter or search."));
  }
  findings.forEach((finding, index) => {
    const details = node("details", "finding");
    details.open = expanded || (index === 0 && finding.status !== "pass");
    const summary = node("summary");
    summary.append(node("span", `badge ${finding.status}`, STATUS_LABEL[finding.status]));
    const heading = node("div");
    heading.append(node("span", "finding-label", finding.label), node("span", "finding-citation", finding.meta),
      node("span", "finding-id", finding.key));
    summary.append(heading);
    const body = node("div", "finding-body");
    const list = node("ul");
    for (const line of finding.detail) list.append(node("li", "", line));
    const policy = scored.requirements[finding.key];
    if (policy) list.append(node("li", "", `Release policy: ${policy}`));
    body.append(list);
    if (finding.span) {
      const button = node("button", "text-button locate-button",
        finding.category === "citation" ? "Show the quote in the contract ↓" : "Show the clause in the contract ↓");
      button.disabled = !isCurrent();
      button.onclick = () => locate(finding);
      body.append(button);
    }
    details.append(summary, body);
    container.append(details);
  });
}

document.querySelectorAll("[data-filter]").forEach(button => {
  button.onclick = () => {
    filter = button.dataset.filter;
    document.querySelectorAll("[data-filter]").forEach(item => item.setAttribute("aria-pressed", String(item === button)));
    renderFindings();
  };
});
$("search").oninput = renderFindings;
$("toggle-all").onclick = () => {
  expanded = !expanded;
  $("toggle-all").textContent = expanded ? "Collapse all" : "Expand all";
  $("toggle-all").setAttribute("aria-pressed", String(expanded));
  renderFindings();
};

function download(text, filename, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = node("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$("download-draft").onclick = () => download(input.value, reviewName || "review.json", "application/json");
// The same names and bytes as `contract-eval score --out`.
$("export-json").onclick = () => {
  if (!busy && isCurrent()) download(scored.result_json, `score-${scored.result.case}.json`, "application/json");
};
$("export-md").onclick = () => {
  if (!busy && isCurrent()) download(scored.markdown, `score-${scored.result.case}.md`, "text/markdown;charset=utf-8");
};
window.addEventListener("beforeunload", event => {
  if (modified) { event.preventDefault(); event.returnValue = ""; }
});

loadSamples();
startRuntime();
