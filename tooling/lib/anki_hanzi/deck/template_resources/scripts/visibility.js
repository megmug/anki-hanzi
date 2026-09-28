  function showHide(selector, isShow, style) {
    document.querySelectorAll(selector).forEach(function (element) {
      element.style.display = isShow ? style || "inline" : "none";
    });
    if (selector === "#char_meaning") {
      var card = document.querySelector(".hanzi-card");
      if (card) card.classList.toggle("has-meaning", !!isShow);
    }
  }
