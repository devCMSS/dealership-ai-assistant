// Two-step delete (no browser confirm dialogs) and double-submit protection.
(function () {
  "use strict";
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (form.matches("[data-confirm]")) {
      var btn = form.querySelector("[data-confirm-label]");
      if (!btn.classList.contains("armed")) {
        event.preventDefault();
        btn.dataset.originalLabel = btn.textContent;
        btn.textContent = btn.dataset.confirmLabel;
        btn.classList.add("armed");
        setTimeout(function () {
          btn.classList.remove("armed");
          btn.textContent = btn.dataset.originalLabel;
        }, 4000);
        return;
      }
    }
    if (form.matches("[data-once]")) {
      if (form.dataset.sent) { event.preventDefault(); return; }
      form.dataset.sent = "1";
      var submit = form.querySelector("[type=submit]");
      if (submit) { submit.disabled = true; submit.textContent = "Saving..."; }
    }
  });
})();
