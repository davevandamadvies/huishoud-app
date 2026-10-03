// Kleine hulpjes voor de bottom sheet. Bewust een los bestand: de CSP staat
// geen inline scripts toe, en htmx-eval (hx-on) staat uit.
(function () {
  "use strict";
  var lastTrigger = null;

  function sheet() {
    return document.getElementById("sheet");
  }

  function isOpen() {
    var s = sheet();
    return s !== null && s.children.length > 0;
  }

  function closeSheet() {
    var s = sheet();
    if (!s) return;
    s.innerHTML = "";
    document.body.classList.remove("sheet-open");
    if (lastTrigger && document.contains(lastTrigger)) lastTrigger.focus();
  }

  document.addEventListener("click", function (event) {
    var opener = event.target.closest("[hx-target='#sheet']");
    if (opener) lastTrigger = opener;
    if (event.target.closest("[data-close-sheet]")) {
      event.preventDefault();
      closeSheet();
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && isOpen()) closeSheet();
  });

  // Puntenstepper: − / + en live verdeling over de gekozen uitvoerders.
  function updateShare(stepper) {
    var note = stepper.querySelector("[data-share]");
    var input = stepper.querySelector("input[name='points']");
    var form = stepper.closest("form");
    if (!note || !input || !form) return;
    var people = form.querySelectorAll("input[name='performer']:checked").length;
    var points = parseInt(input.value, 10);
    note.textContent =
      people > 1 && points > 0 ? "Samen: ieder " + Math.ceil(points / people) : "";
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-step]");
    if (!button) return;
    var stepper = button.closest("[data-stepper]");
    var input = stepper && stepper.querySelector("input[name='points']");
    if (!input) return;
    var value = parseInt(input.value, 10) || 0;
    value = Math.min(100, Math.max(0, value + parseInt(button.dataset.step, 10)));
    input.value = value > 0 ? String(value) : "";
    updateShare(stepper);
  });

  document.addEventListener("input", function (event) {
    var stepper = event.target.closest("form") &&
      event.target.closest("form").querySelector("[data-stepper]");
    if (stepper) updateShare(stepper);
  });

  document.addEventListener("htmx:afterSwap", function (event) {
    var stepper = document.querySelector("#sheet [data-stepper]");
    if (stepper) updateShare(stepper);
    if (event.detail.target.id !== "sheet") return;
    if (!isOpen()) {
      closeSheet();
      return;
    }
    document.body.classList.add("sheet-open");
    var focusable = sheet().querySelector("[data-autofocus], h2");
    if (focusable) focusable.focus();
  });
})();
