  function doPractice(p = false) {
    if (document.getElementById("back")) {
      restoreQuizScoreDisplay();
      generateHanziOnFinishQuiz("unset", true);
      if (!p) {
        showNextAndRevealBtn(false);
        return;
      }
    } else {
      generateHanziOnFinishQuiz("none");
    }

    document.getElementById("ch_load_status").innerHTML = "&#8226;";
    document.getElementById("ch_load_status").style.marginBottom = "0px";
    document.getElementById("ch_load_status").style.display = "block";

    var hanziWriterList = [];
    var quizScore = createQuizScoreTracker(characters.length);
    window.xhActiveQuizScore = quizScore;
    var drawGrid = document.getElementById("character-target-div");
    drawGrid.innerHTML = "";

    for (var i = 0; i < characters.length; i++) {
      (function (characterIndex) {
        var div = document.createElement("div");
        div.id = "div" + characterIndex;
        var hanzi = characters[characterIndex];

        if (isHanzi(hanzi)) {
          div.innerHTML = grid_data;
          div.children[0].id = "grid-background-target" + characterIndex;
          drawGrid.appendChild(div);
          setStrokeColor(characterIndex);
          var writer = HanziWriter.create(
            "grid-background-target" + characterIndex,
            hanzi,
            {
              onLoadCharDataSuccess: function (data) {
                document.getElementById("ch_load_status").style.color =
                  "#4caf50";
                quizScore.setTotalStrokes(characterIndex, data.strokes.length);
              },
              onLoadCharDataError: function (reason) {
                document.getElementById("ch_load_status").style.color =
                  "#ea2322";
                console.error("HanziWriter data missing for:", hanzi, reason);
              },

              width: charWidth,
              height: charHeight,
              showCharacter: false,
              showOutline: WRITE_SETTINGS.show_outline,
              highlightOnComplete: true,
              highlightCompleteColor: stroke_color,
              drawingWidth: strokeWidth,
              strokeColor: stroke_color,
              outlineColor: outline_color,
              drawingColor: drawing_color,
              strokeHighlightSpeed: 0.5,
              showHintAfterMisses: strokeAfterMisses,
              leniency: strokeLeniency,
              acceptBackwardsStrokes: false,
              markStrokeCorrectAfterMisses: false,
              padding: 5,
              charDataLoader: bundleCharDataLoader,
            },
          );

          writerQuiz(writer, characterIndex);
          hanziWriterList.push(writer);
        } else {
          div.style.fontSize = charHeight + "px";
          div.style.lineHeight = charHeight + "px";
          div.style.textAlign = "center";
          div.style.width = charWidth + "px";
          div.style.height = charHeight + "px";
          div.textContent = hanzi;
          drawGrid.appendChild(div);
          quizScore.setTotalStrokes(characterIndex, 0);
          hanziWriterList.push(null);
        }
      })(i);
    }

    observeWriterSize(hanziWriterList);

    var revealClickCount = 0;
    var goNextButton = document.getElementById("btnGoNextCard");
    if (goNextButton) {
      goNextButton.onclick = function () {
        revealClickCount = 0;
        var currentIndex = getCurrentHanziNum();
        var writer = hanziWriterList[currentIndex];
        if (writer) {
          quizScore.markAssist();
          writer.showOutline();
          writer.showCharacter();
          setTimeout(function () {
            onFinishQuizDrawHanzi();
          }, 800);
          setTimeout(function () {
            showNextHanzi();
          }, 1000);
        } else {
          onFinishQuizDrawHanzi();
          showNextHanzi();
        }
      };
    }

    var revealButton = document.getElementById("btnRevealChar");
    if (revealButton) {
      revealButton.onclick = function () {
        var currentIndex = getCurrentHanziNum();
        var writer = hanziWriterList[currentIndex];
        if (!writer) {
          onFinishQuizDrawHanzi();
          showNextHanzi();
          return;
        }
        quizScore.markAssist();
        writer.showOutline();
        if (revealClickCount == 0) {
          writer.animateCharacter();
        } else if (revealClickCount == 1) {
          writer.showCharacter();
        } else if (revealClickCount == 2) {
          writer.hideCharacter();
          writer.hideOutline();
          writerQuiz(writer, currentIndex);
        } else {
          revealClickCount = -1;
          writerQuiz(writer, currentIndex);
        }
        revealClickCount++;
      };
    }

    var hintButton = document.getElementById("btnHintStroke");
    if (hintButton) {
      hintButton.onclick = function () {
        var currentIndex = getCurrentHanziNum();
        var writer = hanziWriterList[currentIndex];
        if (!writer || quizScore.isComplete()) {
          return;
        }

        var strokeNum = quizScore.getCurrentStroke(currentIndex);
        if (strokeNum >= quizScore.getTotalStrokes(currentIndex)) {
          return;
        }

        quizScore.markHint(currentIndex, strokeNum);
        writer.highlightStroke(strokeNum);
      };
    }

    function writerQuiz(writer, characterIndex) {
      writer.quiz({
        onMistake: function (data) {
          quizScore.markMistake();
          if (strokeAfterMisses && data.mistakesOnStroke >= strokeAfterMisses) {
            quizScore.markHint(characterIndex, data.strokeNum);
          }
        },
        onCorrectStroke: function (data) {
          quizScore.markCorrectStroke(characterIndex, data);
        },
        onComplete: function (summaryData) {
          onFinishQuizDrawHanzi();
          revealClickCount = 0;

          setTimeout(function () {
            showNextHanzi();
          }, 1000);
        },
      });
    }

    function getCurrentHanziNum() {
      var characterDiv = document.querySelector("#character-target-div");
      var characterElements = characterDiv.children;
      var len = characterElements.length;
      for (var i = 0; i < len; i++) {
        var style = characterElements[i].style.display;
        if (style === "block" || style === "") {
          return i;
        }
      }
      return 0;
    }

    function onFinishQuizDrawHanzi() {
      var finishCharacterDiv = document.getElementById(
        "onfinish-character-target-div",
      );
      var characterElements = finishCharacterDiv.children;
      var len = characterElements.length;
      for (var i = 0; i < len; i++) {
        var style = characterElements[i].style.display;
        if (style === "none" || style === "") {
          characterElements[i].style.display = "unset";
          break;
        }
      }
    }
  }

  function showNextHanzi() {
    var characterDiv = document.querySelector("#character-target-div");
    var characterElements = characterDiv.children;
    var len = characterElements.length;

    for (var i = 0; i < len; i++) {
      var style = characterElements[i].style.display;
      if (style === "block" || style === "") {
        characterElements[i].style.display = "none";
        characterElements[(i + 1) % characterElements.length].style.display =
          "block";
        onFinishQuiz(i, len);
        break;
      }
    }
  }

  function onFinishQuiz(i, len) {
    if (i != len - 1) {
      return;
    }

    if (i + 1 == len) {
      document.querySelector("#character-target-div").innerHTML = "";
      document.getElementById("ch_load_status").style.display = "none";
      generateHanziOnFinishQuiz("unset", true);
      if (window.xhActiveQuizScore) {
        window.xhActiveQuizScore.markComplete();
      }
      document.querySelector(".hanzi-card").classList.add("writer-complete");
    }

    showHide("#btnHintStroke", false);
    playAudio();
    showHide("#char_sim", true, "block");
    showHide("#char_meaning", true, "block");
    if (WRITE_SETTINGS.show_pinyin) {
      showHide(".pinyin", true);
    }
    showNextAndRevealBtn(false);
  }

  function showNextAndRevealBtn(show) {
    showHide("#btnGoNextCard", show, "inline-flex");
    showHide("#btnRevealChar", show, "inline-flex");
  }

  doPractice();
