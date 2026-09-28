  window.HANZI_CARD_SETTINGS = __HANZI_CARD_SETTINGS__;

  var frontBack = document.getElementById("back") ? "back" : "front";
  var WRITE_SETTINGS =
    (window.HANZI_CARD_SETTINGS && window.HANZI_CARD_SETTINGS[frontBack]) || {};
  var characters = "";

  /* __SHARED_VISIBILITY__ */

  function initWriteSettings() {
    showHide("#char_pinyin", WRITE_SETTINGS.show_pinyin, "block");
    showHide("#char_meaning", WRITE_SETTINGS.show_meaning, "block");
    showHide("#char_sim", WRITE_SETTINGS.show_simplified, "block");
    showHide(".pinyin", WRITE_SETTINGS.show_pinyin);
    showHide("#char-sim-id", WRITE_SETTINGS.show_simplified);

    characters = document.getElementById("char_sim").textContent;
  }

  /* __SHARED_SIDEBAR__ */

  initWriteSettings();
