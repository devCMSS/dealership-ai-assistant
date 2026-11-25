// Chat widget: talks to POST /api/chat. All model text is rendered with textContent.
(function () {
  "use strict";
  var panel = document.getElementById("chat");
  if (!panel) return;
  var log = document.getElementById("chat-log");
  var form = document.getElementById("chat-form");
  var input = document.getElementById("chat-input");
  var suggestions = document.getElementById("chat-suggestions");
  var launcher = document.querySelector(".chat-launcher");
  var vehicleId = parseInt(document.body.dataset.vehicleId, 10) || null;
  var busy = false;

  function store(key, value) { try { sessionStorage.setItem(key, value); } catch (e) {} }
  function load(key) { try { return sessionStorage.getItem(key); } catch (e) { return null; } }

  function sessionId() {
    var id = null;
    try { id = localStorage.getItem("chat_session"); } catch (e) {}
    if (!id || !/^[A-Za-z0-9_-]{16,64}$/.test(id)) {
      id = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(36).slice(2, 12);
      try { localStorage.setItem("chat_session", id); } catch (e) {}
    }
    return id;
  }

  // Transcript survives page navigation within the tab.
  var transcript = [];
  try { transcript = JSON.parse(load("chat_transcript") || "[]"); } catch (e) { transcript = []; }

  function bubble(kind, text) {
    var el = document.createElement("div");
    el.className = "bubble " + kind;
    el.textContent = text;
    log.appendChild(el);
    return el;
  }

  function cards(vehicles) {
    if (!vehicles || !vehicles.length) return;
    var wrap = document.createElement("div");
    wrap.className = "chat-cards";
    vehicles.forEach(function (v) {
      var a = document.createElement("a");
      a.className = "mini-card";
      a.href = "/vehicles/" + encodeURIComponent(v.id);
      var title = document.createElement("strong");
      title.textContent = v.title;
      var price = document.createElement("span");
      price.textContent = "$" + Number(v.price).toLocaleString("en-US");
      a.appendChild(title);
      a.appendChild(price);
      wrap.appendChild(a);
    });
    log.appendChild(wrap);
  }

  function render(entry) {
    if (entry.role === "user") bubble("user", entry.text);
    else if (entry.role === "note") bubble("note", entry.text);
    else { bubble("bot", entry.text); cards(entry.vehicles); }
  }

  function remember(entry) {
    transcript.push(entry);
    transcript = transcript.slice(-40);
    store("chat_transcript", JSON.stringify(transcript));
    render(entry);
    log.scrollTop = log.scrollHeight;
  }

  function greet() {
    if (transcript.length) { transcript.forEach(render); return; }
    remember({ role: "bot", text: "Hi! I know every car on our lot right now. What are you looking for?" });
  }

  function open(prefill) {
    panel.hidden = false;
    if (launcher) { launcher.hidden = true; launcher.setAttribute("aria-expanded", "true"); }
    if (!log.childElementCount) greet();
    if (prefill) input.value = prefill;
    input.focus();
    log.scrollTop = log.scrollHeight;
  }

  function close() {
    panel.hidden = true;
    if (launcher) { launcher.hidden = false; launcher.setAttribute("aria-expanded", "false"); launcher.focus(); }
  }

  function send(text) {
    text = (text || "").trim();
    if (!text || busy) return;
    busy = true;
    form.querySelector("button").disabled = true;
    remember({ role: "user", text: text });
    input.value = "";
    if (suggestions) suggestions.hidden = true;
    var typing = bubble("bot typing", "Typing...");
    log.scrollTop = log.scrollHeight;

    fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId(), message: text, vehicle_id: vehicleId })
    })
      .then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (data) { return { ok: res.ok, data: data }; });
      })
      .then(function (r) {
        typing.remove();
        if (!r.ok) {
          var detail = typeof r.data.detail === "string" ? r.data.detail : "Sorry, I couldn't send that. Please try again.";
          remember({ role: "note", text: detail });
          return;
        }
        remember({ role: "bot", text: r.data.reply, vehicles: r.data.vehicles });
        if (r.data.lead_saved && !load("lead_noted")) {
          store("lead_noted", "1");
          remember({ role: "note", text: "Your details were shared with a sales advisor." });
        }
      })
      .catch(function () {
        typing.remove();
        remember({ role: "note", text: "Connection problem. Check your internet and try again." });
      })
      .finally(function () {
        busy = false;
        form.querySelector("button").disabled = false;
        input.focus();
      });
  }

  document.addEventListener("click", function (event) {
    var opener = event.target.closest("[data-chat-open]");
    if (opener) { open(opener.dataset.chatPrefill || ""); return; }
    if (event.target.closest("[data-chat-close]")) close();
  });
  if (suggestions) {
    suggestions.addEventListener("click", function (event) {
      var btn = event.target.closest("button");
      if (btn) send(btn.textContent);
    });
  }
  form.addEventListener("submit", function (event) { event.preventDefault(); send(input.value); });
  panel.addEventListener("keydown", function (event) { if (event.key === "Escape") close(); });

  // Inventory filters apply as soon as a select changes; search waits for typing to pause.
  var filters = document.querySelector("form[data-autosubmit]");
  if (filters) {
    var timer;
    filters.addEventListener("change", function (e) { if (e.target.tagName === "SELECT") filters.submit(); });
    filters.addEventListener("input", function (e) {
      if (e.target.type !== "search") return;
      clearTimeout(timer);
      timer = setTimeout(function () { filters.submit(); }, 600);
    });
  }
})();
