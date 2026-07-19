// Client-side archive filtering. Operates on the cards already in the DOM
// (each carries data-source / data-tags / data-date / data-text), so it works
// offline with no fetch. Facets: text query, source, tag, month.
(function () {
  var q = document.getElementById("q");
  var source = document.getElementById("source");
  var tag = document.getElementById("tag");
  var month = document.getElementById("month");
  var clear = document.getElementById("clear");
  var count = document.getElementById("count");
  var cards = Array.prototype.slice.call(
    document.querySelectorAll("#results .post-card")
  );

  function apply() {
    var qv = (q.value || "").trim().toLowerCase();
    var sv = source.value;
    var tv = tag.value;
    var mv = month.value; // "YYYY-MM" or ""
    var shown = 0;

    cards.forEach(function (card) {
      var text = card.getAttribute("data-text") || "";
      var csrc = card.getAttribute("data-source") || "";
      var ctags = (card.getAttribute("data-tags") || "").split(",");
      var cdate = card.getAttribute("data-date") || "";

      var ok =
        (!qv || text.indexOf(qv) !== -1) &&
        (!sv || csrc === sv) &&
        (!tv || ctags.indexOf(tv) !== -1) &&
        (!mv || cdate.indexOf(mv) === 0);

      card.style.display = ok ? "" : "none";
      if (ok) shown++;
    });

    count.textContent = shown + (shown === 1 ? " post" : " posts");
  }

  [q, source, tag, month].forEach(function (el) {
    if (!el) return;
    el.addEventListener("input", apply);
    el.addEventListener("change", apply);
  });
  if (clear) {
    clear.addEventListener("click", function () {
      q.value = ""; source.value = ""; tag.value = ""; month.value = "";
      apply();
    });
  }
})();
