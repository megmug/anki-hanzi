  function getQuizScoreSuggestion(state) {
    var score = Number(state.score) || 0;
    var isPerfect =
      score >= 100 &&
      (Number(state.totalStrokes) || 0) > 0 &&
      Number(state.correctStrokes) === Number(state.totalStrokes) &&
      (Number(state.mistakes) || 0) === 0 &&
      (Number(state.assists) || 0) === 0;
    if (isPerfect) {
      return { label: "Easy", className: "xh-score-easy" };
    }
    if (score >= 75) {
      return { label: "Good", className: "xh-score-good" };
    }
    if (score >= 60) {
      return { label: "Hard", className: "xh-score-hard" };
    }
    return { label: "Again", className: "xh-score-again" };
  }

  function getQuizScoreStorageKey() {
    return "xh-writer-score:" + characters + "::{{text:Pinyin}}";
  }

  function renderQuizScoreState(state) {
    var suggestion = getQuizScoreSuggestion(state);
    var panel = document.getElementById("xh-score-panel");
    var isBack = !!document.getElementById("back");
    var isRevealed = isBack || state.isComplete;

    if (!panel) {
      return;
    }

    document.getElementById("xh-score-value").textContent = isRevealed
      ? state.score + " / 100"
      : "-- / 100";
    document.getElementById("xh-score-suggestion").textContent = isRevealed
      ? suggestion.label
      : "--";
    document.getElementById("xh-score-strokes").textContent = isRevealed
      ? state.correctStrokes +
        " / " +
        (state.totalStrokes ? state.totalStrokes : "-")
      : state.correctStrokes;
    document.getElementById("xh-score-mistakes").textContent = state.mistakes;
    document.getElementById("xh-score-assists").textContent = state.assists;

    panel.classList.remove(
      "xh-score-again",
      "xh-score-hard",
      "xh-score-good",
      "xh-score-easy",
      "xh-score-redacted",
    );
    if (isRevealed) {
      panel.classList.add(suggestion.className);
    } else {
      panel.classList.add("xh-score-redacted");
    }
  }

  function saveQuizScoreState(state) {
    if (!(window.Persistence && Persistence.isAvailable())) {
      return;
    }
    Persistence.setItem(getQuizScoreStorageKey(), JSON.stringify(state));
  }

  function loadQuizScoreState() {
    if (!(window.Persistence && Persistence.isAvailable())) {
      return null;
    }
    try {
      return JSON.parse(Persistence.getItem(getQuizScoreStorageKey()));
    } catch (e) {
      return null;
    }
  }

  function restoreQuizScoreDisplay() {
    var savedState = loadQuizScoreState();
    if (savedState) {
      renderQuizScoreState(savedState);
    }
  }

  function createQuizScoreTracker(characterCount) {
    var mistakePenaltyStrokeRatio = 0.8;
    var hintPenaltyStrokeRatio = 1.2;
    var totalStrokesByChar = [];
    var correctStrokesByChar = [];
    var hintedStrokes = {};
    var mistakes = 0;
    var hintAssists = 0;
    var isComplete = false;

    for (var i = 0; i < characterCount; i++) {
      totalStrokesByChar.push(0);
      correctStrokesByChar.push(0);
    }

    function sum(values) {
      return values.reduce(function (total, value) {
        return total + (Number(value) || 0);
      }, 0);
    }

    function clampScore(value) {
      return Math.max(0, Math.min(100, Math.round(value)));
    }

    function updateDisplay() {
      var totalStrokes = sum(totalStrokesByChar);
      var correctStrokes = sum(correctStrokesByChar);
      var baseScore = totalStrokes ? (correctStrokes / totalStrokes) * 100 : 0;
      var pointsPerStroke = totalStrokes ? 100 / totalStrokes : 0;
      var mistakePenalty = pointsPerStroke * mistakePenaltyStrokeRatio;
      var hintPenalty = hintAssists * pointsPerStroke * hintPenaltyStrokeRatio;
      var score = clampScore(
        baseScore - mistakes * mistakePenalty - hintPenalty,
      );
      var state = {
        score: score,
        correctStrokes: correctStrokes,
        totalStrokes: totalStrokes,
        mistakes: mistakes,
        assists: hintAssists,
        isComplete: isComplete,
      };

      renderQuizScoreState(state);
      saveQuizScoreState(state);
    }

    updateDisplay();

    return {
      setTotalStrokes: function (characterIndex, totalStrokes) {
        totalStrokesByChar[characterIndex] = Number(totalStrokes) || 0;
        updateDisplay();
      },
      markCorrectStroke: function (characterIndex, data) {
        correctStrokesByChar[characterIndex] = Math.max(
          correctStrokesByChar[characterIndex] || 0,
          Number(data.strokeNum) + 1,
        );
        updateDisplay();
      },
      markMistake: function () {
        mistakes++;
        updateDisplay();
      },
      markComplete: function () {
        isComplete = true;
        updateDisplay();
      },
      markHint: function (characterIndex, strokeNum) {
        var key = characterIndex + ":" + strokeNum;
        if (!hintedStrokes[key]) {
          hintedStrokes[key] = true;
          hintAssists++;
          updateDisplay();
        }
      },
      getCurrentStroke: function (characterIndex) {
        return correctStrokesByChar[characterIndex] || 0;
      },
      getTotalStrokes: function (characterIndex) {
        return totalStrokesByChar[characterIndex] || 0;
      },
      isComplete: function () {
        return isComplete;
      },
    };
  }
