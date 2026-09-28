  var stroke = WRITE_SETTINGS.show_grid ? "var(--surface1)" : "";

  var grid_data = `<svg xmlns='http://www.w3.org/2000/svg' width='100%' height='100%' class='grid-color'  id='grid-background-target'><g id="char_grid"><line x1='0' y1='0' x2='100%' y2='100%' stroke='${stroke}' /><line x1='100%' y1='0' x2='0' y2='100%' stroke='${stroke}' /><line x1='50%' y1='0' x2='50%' y2='100%' stroke='${stroke}' /><line x1='0' y1='50%' x2='100%' y2='50%' stroke='${stroke}' /></g></svg>`;

  function isHanzi(char) {
    var code = char.charCodeAt(0);
    return (
      (code >= 0x4e00 && code <= 0x9fff) ||
      (code >= 0x3400 && code <= 0x4dbf) ||
      (code >= 0x20000 && code <= 0x2ebef)
    );
  }

  function generateHanziOnFinishQuiz(style = "none", finish = false) {
    var drawGrid = document.getElementById("onfinish-character-target-div");
    if (!drawGrid) {
      return;
    }
    drawGrid.innerHTML = "";
    var size = finish ? 72 : 32;

    for (var i = 0; i < characters.length; i++) {
      var hanzi = characters[i];
      var span = document.createElement("span");
      if (isHanzi(hanzi)) {
        span.innerHTML = grid_data;
        span.children[0].id = "onfinish-grid-background-target" + i;
        span.style.display = style;
        drawGrid.appendChild(span);
        setStrokeColor(i);
        var writer = HanziWriter.create(
          "onfinish-grid-background-target" + i,
          hanzi,
          {
            width: size,
            height: size,
            padding: 5,
            strokeColor: stroke_color,
            charDataLoader: bundleCharDataLoader,
          },
        );
      } else {
        span.style.display = style;
        span.style.fontSize = size + "px";
        span.style.lineHeight = size + "px";
        span.style.verticalAlign = "middle";
        span.textContent = hanzi;
        drawGrid.appendChild(span);
      }
    }
  }
