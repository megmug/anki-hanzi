  // Hanzi Writer 3.7.3 has no public disposal API. Keep the adaptation here:
  // its default pointer-end listeners otherwise retain every writer on document.
  var CardHanziWriter = class extends HanziWriter {
    _setupListeners() {
      this.removeEndListeners = [];
      this.target.addPointerEndListener = (callback) => {
        ["mouseup", "touchend"].forEach((event) => {
          this.removeEndListeners.push(cardRuntime.listen(document, event, callback));
        });
      };
      super._setupListeners();
    }

    _withData(callback) {
      return super._withData(() => {
        if (!this.disposed && cardRuntime.isActive()) return callback();
      });
    }

    dispose() {
      this.disposed = true;
      this.removeEndListeners.splice(0).forEach(function (remove) { remove(); });
      if (this.unregisterCleanup) this.unregisterCleanup();
      this.cancelQuiz();
      if (this._renderState) this._renderState.cancelAll();
    }
  };

  function createCardWriter(target, character, options) {
    var writer = new CardHanziWriter(target, options);
    writer.unregisterCleanup = cardRuntime.onCleanup(function () { writer.dispose(); });
    writer.setCharacter(character).then(function () {
      // Loading may finish after a quick flip. Cancel any state created meanwhile.
      if (writer.disposed || !cardRuntime.isActive()) writer.dispose();
    });
    return writer;
  }

  function disposeWriters(writers) {
    writers.forEach(function (writer) { if (writer) writer.dispose(); });
    writers.length = 0;
  }

  var practiceWriters = [];
  var thumbnailWriters = [];
