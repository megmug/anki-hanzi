  function openSidebar(id) {
    var sidebar = document.getElementById(id);
    if (sidebar) {
      sidebar.style.width = "min(300px, 90vw)";
    }
  }

  function closeSidebar(id) {
    var sidebar = document.getElementById(id);
    if (sidebar) {
      sidebar.style.width = "0";
    }
  }

  window.hanziCardRuntime.listen(document, "click", function (event) {
    var moreInfoSidebar = document.getElementById("more-info-sidebar");
    var moreInfoButton = document.getElementById("btnMoreOptions");
    if (!moreInfoSidebar || !moreInfoButton) {
      return;
    }
    if (!moreInfoSidebar.contains(event.target)) {
      closeSidebar("more-info-sidebar");
    }
    if (moreInfoButton.contains(event.target)) {
      openSidebar("more-info-sidebar");
    }
  });
