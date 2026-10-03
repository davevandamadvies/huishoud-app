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

  // Meldingen aan/uit op dit toestel (pagina Meldingen).
  function base64UrlToBytes(value) {
    var padded = (value + "===".slice((value.length + 3) % 4)).replace(/-/g, "+").replace(/_/g, "/");
    var raw = atob(padded);
    var bytes = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    return bytes;
  }

  function pushParts(root) {
    return {
      status: root.querySelector("[data-push-status]"),
      on: root.querySelector("[data-push-subscribe]"),
      off: root.querySelector("[data-push-unsubscribe]"),
    };
  }

  function pushSupported() {
    return "serviceWorker" in navigator && "PushManager" in window &&
      "Notification" in window && window.isSecureContext;
  }

  function showPushState(root) {
    var parts = pushParts(root);
    if (!parts.status) return;
    if (!pushSupported()) {
      parts.status.textContent = "Deze browser ondersteunt geen meldingen. Open de app in Chrome of installeer hem op je startscherm.";
      return;
    }
    if (Notification.permission === "denied") {
      parts.status.textContent = "Meldingen zijn geblokkeerd. Sta ze toe in de instellingen van je browser of telefoon.";
      return;
    }
    navigator.serviceWorker.ready.then(function (registration) {
      return registration.pushManager.getSubscription();
    }).then(function (subscription) {
      parts.status.textContent = subscription
        ? "Meldingen staan aan op dit toestel."
        : "Meldingen staan uit op dit toestel.";
      parts.on.hidden = Boolean(subscription);
      parts.off.hidden = !subscription;
    });
  }

  function pushSubscribe(root) {
    var parts = pushParts(root);
    Notification.requestPermission().then(function (permission) {
      if (permission !== "granted") {
        showPushState(root);
        return null;
      }
      return navigator.serviceWorker.ready.then(function (registration) {
        return registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: base64UrlToBytes(root.dataset.pushKey),
        });
      });
    }).then(function (subscription) {
      if (!subscription) return;
      var data = subscription.toJSON();
      htmx.ajax("POST", "/meldingen/abonneren", {
        target: "#push-panel",
        swap: "innerHTML",
        values: { endpoint: data.endpoint, p256dh: data.keys.p256dh, auth: data.keys.auth },
      });
    }).catch(function () {
      parts.status.textContent = "Aanzetten lukte niet. Probeer het later opnieuw.";
    });
  }

  function pushUnsubscribe() {
    navigator.serviceWorker.ready.then(function (registration) {
      return registration.pushManager.getSubscription();
    }).then(function (subscription) {
      if (!subscription) return null;
      var endpoint = subscription.endpoint;
      return subscription.unsubscribe().then(function () {
        htmx.ajax("POST", "/meldingen/afmelden", {
          target: "#push-panel",
          swap: "innerHTML",
          values: { endpoint: endpoint },
        });
      });
    });
  }

  document.addEventListener("click", function (event) {
    var root = event.target.closest("[data-push]");
    if (!root) return;
    if (event.target.closest("[data-push-subscribe]")) pushSubscribe(root);
    if (event.target.closest("[data-push-unsubscribe]")) pushUnsubscribe();
  });

  function initPush() {
    var root = document.querySelector("[data-push]");
    if (root) showPushState(root);
  }

  document.addEventListener("DOMContentLoaded", initPush);
  document.addEventListener("htmx:afterSettle", function (event) {
    if (event.detail.target.id === "push-panel") initPush();
  });

  // Service worker registreren (voor meldingen en de offline-pagina).
  if ("serviceWorker" in navigator && window.isSecureContext) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () {
        // Geen service worker: de app werkt gewoon, alleen zonder meldingen.
      });
    });
  }
})();
