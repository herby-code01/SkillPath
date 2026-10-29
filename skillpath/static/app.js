// Remember the browser's UTC offset so the server can show dates in local time.
(function () {
  try {
    document.cookie = "tzo=" + new Date().getTimezoneOffset() + ";path=/;max-age=31536000;samesite=lax";
  } catch (e) { /* cookies disabled: the server falls back to UTC */ }

  // Confirm destructive actions declared with data-confirm.
  document.addEventListener("submit", function (ev) {
    var msg = ev.target.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) { ev.preventDefault(); }
  });
})();
