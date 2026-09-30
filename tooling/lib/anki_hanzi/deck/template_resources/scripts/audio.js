  function collectAudioElements() {
    var audioDiv = document.getElementById("audio");
    if (!audioDiv) return [];
    var allChildren = audioDiv.getElementsByTagName("*");
    var audioElements = [];
    for (var i = 0; i < allChildren.length; i++) {
      var tag = allChildren[i].tagName;
      if (tag === "AUDIO" || tag === "A") {
        audioElements.push(allChildren[i]);
      }
    }
    return audioElements;
  }

  function playAudio() {
    var runtime = window.hanziCardRuntime;
    var audioElements = collectAudioElements();
    if (audioElements.length === 0) return;

    function playNext(index) {
      if (!runtime.isActive() || index >= audioElements.length) return;
      var el = audioElements[index];
      if (el.tagName === "AUDIO") {
        el.onended = function () {
          playNext(index + 1);
        };
        el.play();
      } else {
        el.click();
        // Anki <a> sound links have no onended event; chain with a fixed delay
        runtime.timeout(function () {
          playNext(index + 1);
        }, 1500);
      }
    }
    playNext(0);
  }
