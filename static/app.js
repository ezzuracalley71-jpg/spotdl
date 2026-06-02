const form = document.querySelector("#download-form");
const submit = document.querySelector("#submit");
const health = document.querySelector("#health");
const jobTitle = document.querySelector("#job-title");
const jobState = document.querySelector("#job-state");
const log = document.querySelector("#log");
const files = document.querySelector("#files");
const refresh = document.querySelector("#refresh");
const queryInput = document.querySelector("#query");
const formatInput = document.querySelector("#format");
const bitrateInput = document.querySelector("#bitrate");
const overwriteInput = document.querySelector("#overwrite");

let activeJob = null;
let pollTimer = null;

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let size = bytes / 1024;
  let unit = units.shift();
  while (size >= 1024 && units.length) {
    size /= 1024;
    unit = units.shift();
  }
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${unit}`;
}

function setState(state) {
  jobState.textContent = state;
  jobState.classList.toggle("failed", state === "failed");
  jobState.classList.toggle("muted", state === "ready" || state === "idle");
}

async function checkHealth() {
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    health.textContent = data.ok ? "Ready" : "Missing spotdl";
    health.classList.toggle("failed", !data.ok);
  } catch {
    health.textContent = "Offline";
    health.classList.add("failed");
  }
}

async function loadFiles() {
  const response = await fetch("/api/files");
  const data = await response.json();
  files.innerHTML = "";

  if (!data.files.length) {
    files.innerHTML = '<div class="empty">No audio files yet.</div>';
    return;
  }

  for (const file of data.files) {
    const row = document.createElement("div");
    row.className = "file-row";
    const modified = new Date(file.modified_at).toLocaleString();
    row.innerHTML = `
      <div>
        <div class="file-name"></div>
        <div class="file-meta">${formatBytes(file.size)} · ${modified}</div>
      </div>
      <audio controls preload="none" src="${file.url}"></audio>
      <a href="${file.url}" download>Save</a>
    `;
    row.querySelector(".file-name").textContent = file.name;
    files.appendChild(row);
  }
}

async function pollJob() {
  if (!activeJob) return;
  const response = await fetch(`/api/downloads/${activeJob}`);
  const data = await response.json();
  jobTitle.textContent = data.query;
  setState(data.status);
  log.textContent = data.log.length ? data.log.join("\n") : "Starting...";
  log.scrollTop = log.scrollHeight;

  if (data.status === "complete" || data.status === "failed") {
    clearInterval(pollTimer);
    pollTimer = null;
    submit.disabled = false;
    submit.textContent = "Download";
    await loadFiles();
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  submit.disabled = true;
  submit.textContent = "Starting";
  setState("queued");
  log.textContent = "Creating download job...";

  const payload = {
    query: queryInput.value,
    format: formatInput.value,
    bitrate: bitrateInput.value,
    overwrite: overwriteInput.value,
  };

  try {
    const response = await fetch("/api/downloads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Download failed to start.");
    }

    activeJob = data.id;
    jobTitle.textContent = data.query;
    setState(data.status);
    await pollJob();
    pollTimer = setInterval(pollJob, 1400);
  } catch (error) {
    submit.disabled = false;
    submit.textContent = "Download";
    setState("failed");
    log.textContent = error.message;
  }
});

refresh.addEventListener("click", loadFiles);

checkHealth();
loadFiles();
