  function getWriterSize(configuredSize) {
    var configured = parseInt(configuredSize, 10);
    if (!isFinite(configured) || configured <= 0) {
      configured = 400;
    }

    var space = document.querySelector(".writer-canvas-space");
    var bounds = space.getBoundingClientRect();
    var available = Math.floor(Math.min(bounds.width, bounds.height));
    if (!isFinite(available) || available <= 0) {
      return configured;
    }
    return Math.max(100, Math.min(configured, available));
  }

  var configuredCharHW = parseInt(WRITE_SETTINGS.grid_size, 10);
  if (!isFinite(configuredCharHW) || configuredCharHW <= 0) {
    configuredCharHW = 400;
  }
  var charHW = getWriterSize(configuredCharHW);
  var charHeight = charHW;
  var charWidth = charHW;
  function setWriterSurfaceSize(size) {
    var target = document.getElementById("character-target-div");
    target.style.width = target.style.height = size + "px";
  }
  setWriterSurfaceSize(charHW);
  if (window.hanziWriterResizeObserver) {
    window.hanziWriterResizeObserver.disconnect();
  }

  function observeWriterSize(writers) {
    if (typeof ResizeObserver === "undefined") return;
    var space = document.querySelector(".writer-canvas-space");
    var targets = document.getElementById("character-target-div");
    var observer = new ResizeObserver(function () {
      if (!space.isConnected) {
        observer.disconnect();
        return;
      }
      if (!space.clientHeight) return;
      var size = getWriterSize(configuredCharHW);
      if (size === charHW) return;
      charHW = charWidth = charHeight = size;
      setWriterSurfaceSize(size);
      // Resize existing writers so rotating the screen preserves the active quiz.
      writers.forEach(function (writer, index) {
        if (writer) {
          writer.updateDimensions({ width: size, height: size });
        } else if (targets.children[index]) {
          var target = targets.children[index];
          target.style.width = target.style.height = size + "px";
          target.style.fontSize = target.style.lineHeight = size + "px";
        }
      });
    });
    observer.observe(space);
    window.hanziWriterResizeObserver = observer;
  }
  var configuredStrokeWidth = Number(WRITE_SETTINGS.stroke_width);
  if (!isFinite(configuredStrokeWidth) || configuredStrokeWidth <= 0) {
    configuredStrokeWidth = 64;
  }
  var strokeWidth = Math.max(
    2,
    Math.round(configuredStrokeWidth * (charHW / configuredCharHW)),
  );
  function getHintAfterMisses(value) {
    var parsed = parseInt(value, 10);
    return parsed > 0 ? parsed : false;
  }

  var strokeAfterMisses = getHintAfterMisses(WRITE_SETTINGS.hint_after_misses);
  var strokeLeniency = Number(WRITE_SETTINGS.stroke_leniency);
  if (!isFinite(strokeLeniency) || strokeLeniency <= 0) {
    strokeLeniency = 1;
  }
