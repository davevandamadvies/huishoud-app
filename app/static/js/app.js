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

  document.addEventListener("htmx:afterSwap", function (event) {
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
