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

  function updateViewport() {
    if (!isActive() || document.hidden) return;
    var viewport = window.visualViewport;
    // Pinch zoom should magnify the card, not cause it to reflow continuously.
    if (viewport && viewport.scale !== 1) return;
    var height = viewport ? Math.min(window.innerHeight, viewport.height) : window.innerHeight;
    var top = Math.max(0, screen.getBoundingClientRect().top + window.scrollY);
    var available = Math.floor(height - top);
    if (available > 0 && screen.style.getPropertyValue("--hanzi-viewport-height") !== available + "px") {
      screen.style.setProperty("--hanzi-viewport-height", available + "px");
    }
  }

  var viewportFrame = null;
  function scheduleViewport() {
    if (viewportFrame !== null) return;
    viewportFrame = requestAnimationFrame(function () {
      viewportFrame = null;
      updateViewport();
    });
  }
  onCleanup(function () {
    if (viewportFrame !== null) cancelAnimationFrame(viewportFrame);
  });

  var viewportRetry = null;
  function settleViewport() {
    if (viewportRetry !== null) {
      clearTimeout(viewportRetry);
      timers.delete(viewportRetry);
      viewportRetry = null;
    }
    if (!isActive() || document.hidden) return;
    scheduleViewport();
    // Webviews can settle after the first frame without another resize event.
    // Keep one pending retry; the card lifecycle cancels it on replacement.
    var delays = [100, 250, 500, 1000, 2000];
    function retry(index) {
      var delay = delays[index] - (index === 0 ? 0 : delays[index - 1]);
      viewportRetry = timeout(function () {
        viewportRetry = null;
        scheduleViewport();
        if (index + 1 < delays.length) retry(index + 1);
      }, delay);
    }
    retry(0);
  }

  listen(window, "resize", settleViewport);
  listen(document, "visibilitychange", settleViewport);
  if (window.visualViewport) {
    listen(window.visualViewport, "resize", settleViewport);
    listen(window.visualViewport, "scroll", scheduleViewport);
  }
  updateViewport();
  settleViewport();
  if (document.fonts) document.fonts.ready.then(function () {
    if (isActive()) scheduleViewport();
  });
})();
