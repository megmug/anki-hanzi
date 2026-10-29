  window.HANZI_CARD_SETTINGS = __HANZI_CARD_SETTINGS__;

  var WRITE_SETTINGS = window.HANZI_CARD_SETTINGS;
  var characters = "";

  /* __SHARED_VISIBILITY__ */

  function initWriteSettings() {
    var isAnswer = !!document.getElementById("back");
    showHide("#char_pinyin", WRITE_SETTINGS.show_pinyin, "block");
    showHide("#char_meaning", WRITE_SETTINGS.show_meaning, "block");
    showHide("#char_sim", isAnswer, "block");
    showHide(".pinYinWrapper", WRITE_SETTINGS.show_pinyin);
    showHide("#char-sim-id", isAnswer);

    characters = document.getElementById("char_sim").textContent;
  }

  /* __SHARED_SIDEBAR__ */

  initWriteSettings();
