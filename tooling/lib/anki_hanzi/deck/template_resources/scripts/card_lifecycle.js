(function () {
  if (window.hanziCardRuntime) window.hanziCardRuntime.dispose();

  var screen = document.querySelector(".hanzi-screen");
  var cleanups = new Set();
  var timers = new Set();
  var disposed = false;

  function isActive() {
    return !disposed && screen.isConnected;
  }

  function onCleanup(callback) {
    cleanups.add(callback);
    return function () { cleanups.delete(callback); };
  }

  function listen(target, event, callback, options) {
    target.addEventListener(event, callback, options);
    function remove() {
      target.removeEventListener(event, callback, options);
      cleanups.delete(remove);
    }
    onCleanup(remove);
    return remove;
  }

  function timeout(callback, delay) {
    var id = setTimeout(function () {
      timers.delete(id);
      if (isActive()) callback();
    }, delay);
    timers.add(id);
    return id;
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    timers.forEach(clearTimeout);
    timers.clear();
    Array.from(cleanups).reverse().forEach(function (cleanup) { cleanup(); });
    cleanups.clear();
    window.xhActiveQuizScore = null;
  }

  window.hanziCardRuntime = {
    isActive: isActive, onCleanup: onCleanup, listen: listen,
    timeout: timeout, dispose: dispose,
  };

  // Anki can replace the card DOM without navigating or unloading the webview.
  var removalObserver = new MutationObserver(function () {
    if (!screen.isConnected) dispose();
  });
  removalObserver.observe(document.body, { childList: true, subtree: true });
  onCleanup(function () { removalObserver.disconnect(); });
  listen(window, "pagehide", dispose);
})();
