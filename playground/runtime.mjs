// Python runs off the UI thread. Only static code and packages are fetched; the review never leaves the tab.
let pyodide;
const progress = text => self.postMessage({ type: "progress", text });

self.onmessage = async ({ data }) => {
  try {
    if (data.type === "init") {
      progress("Loading Python runtime…");
      const { loadPyodide } = await import("https://cdn.jsdelivr.net/pyodide/v0.29.3/full/pyodide.mjs");
      pyodide = await loadPyodide();
      progress("Loading the scorer…");
      // Pydantic is the package's only dependency and ships with Pyodide, so the wheel installs without resolving.
      await pyodide.loadPackage(["micropip", "pydantic"]);
      if (!("pydantic" in pyodide.loadedPackages)) throw new Error("pydantic did not load");
      pyodide.globals.set("wheel_url", data.wheelUrl);
      await pyodide.runPythonAsync("import micropip\nawait micropip.install(wheel_url, deps=False)");
      pyodide.globals.delete("wheel_url");
      const response = await fetch(new URL("score.py", import.meta.url));
      if (!response.ok) throw new Error("The browser bridge could not be loaded.");
      await pyodide.runPythonAsync(await response.text());
      self.postMessage({ type: "ready" });
    } else if (data.type === "score") {
      const inputs = { review_text: data.text, review_case: data.case, review_aliases: data.aliases, review_name: data.name ?? "" };
      for (const [key, value] of Object.entries(inputs)) pyodide.globals.set(key, value);
      try {
        const result = JSON.parse(await pyodide.runPythonAsync("score_text(review_text, review_case, review_aliases, review_name)"));
        // A refused input carries the CLI's own message, e.g. which field fails the review schema.
        if (result.error) self.postMessage({ type: "error", id: data.id, text: result.error });
        else self.postMessage({ type: "result", id: data.id, ...result });
      } finally {
        for (const key of Object.keys(inputs)) pyodide.globals.delete(key);
      }
    }
  } catch {
    // No Python traceback reaches the page.
    self.postMessage({
      type: "error", id: data.id,
      text: data.type === "init"
        ? "The scorer could not load. Check your connection and retry. Your review is still here."
        : "The score could not finish. Check the review structure and try again. Your review is still here.",
    });
  }
};
