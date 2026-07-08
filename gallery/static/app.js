// Gallery web UI — vanilla JS, no build step, no dependencies.
(function () {
  var section = document.querySelector(".request-detail");
  if (!section) return; // not a request detail page

  var reqId = section.dataset.reqId;
  var kind = section.dataset.kind;
  var status = section.dataset.status;

  var variants = Array.prototype.slice.call(section.querySelectorAll(".variant"));
  var beforeReview = section.querySelector("[data-before-review]");
  var beforeButtons = beforeReview ? Array.prototype.slice.call(beforeReview.querySelectorAll("[data-before-view]")) : [];
  var sideBySideView = beforeReview ? beforeReview.querySelector("[data-side-by-side]") : null;
  var toggleView = beforeReview ? beforeReview.querySelector("[data-before-toggle]") : null;
  var toggleFrame = beforeReview ? beforeReview.querySelector("[data-toggle-frame]") : null;
  var toggleCandidates = beforeReview ? Array.prototype.slice.call(beforeReview.querySelectorAll("[data-toggle-candidate]")) : [];
  var commentBox = section.querySelector(".comment-box");
  var decideBtn = document.getElementById("decide-btn");

  // order[] holds selected variant indices in the order they were tapped.
  // For pick-one/approve this is at most one element; for rank, order matters.
  var order = [];
  var pickOneKinds = { "pick-one": true, "before-after": true };
  var blinkTimer = null;

  function idxOf(el) {
    return parseInt(el.dataset.idx, 10);
  }

  function renderSelection() {
    variants.forEach(function (el) {
      var i = idxOf(el);
      var pos = order.indexOf(i);
      var badge = el.querySelector(".order-badge");
      if (pos === -1) {
        el.classList.remove("selected");
        if (el.hasAttribute("aria-pressed")) el.setAttribute("aria-pressed", "false");
        badge.hidden = true;
      } else {
        el.classList.add("selected");
        if (el.hasAttribute("aria-pressed")) el.setAttribute("aria-pressed", "true");
        if (kind === "rank") {
          badge.hidden = false;
          badge.textContent = String(pos + 1);
        } else {
          badge.hidden = true;
        }
      }
    });
  }

  function isToggleMode() {
    return beforeReview && beforeReview.dataset.mode === "toggle";
  }

  function selectedToggleIdx() {
    return order.length ? order[order.length - 1] : null;
  }

  function syncToggleFrame() {
    if (!toggleFrame) return;
    var selected = selectedToggleIdx();
    toggleFrame.classList.toggle("has-candidate", selected !== null);
    if (selected === null) {
      toggleFrame.classList.remove("show-before");
    }
    toggleCandidates.forEach(function (el) {
      el.hidden = parseInt(el.dataset.toggleCandidate, 10) !== selected;
    });
  }

  function blinkToggleFrame() {
    if (!toggleFrame || !isToggleMode() || selectedToggleIdx() === null) return;
    window.clearTimeout(blinkTimer);
    syncToggleFrame();
    toggleFrame.classList.add("show-before");
    blinkTimer = window.setTimeout(function () {
      toggleFrame.classList.remove("show-before");
    }, 360);
  }

  function setBeforeView(view) {
    if (!beforeReview) return;
    var normalized = view === "toggle" ? "toggle" : "side-by-side";
    beforeReview.dataset.mode = normalized;
    if (sideBySideView) sideBySideView.hidden = normalized !== "side-by-side";
    if (toggleView) toggleView.hidden = normalized !== "toggle";
    beforeButtons.forEach(function (btn) {
      btn.setAttribute("aria-pressed", btn.dataset.beforeView === normalized ? "true" : "false");
    });
    syncToggleFrame();
  }

  function toggleVariant(el) {
    var i = idxOf(el);
    var pos = order.indexOf(i);
    if (isToggleMode() && pos !== -1) {
      blinkToggleFrame();
      return;
    }
    if (pickOneKinds[kind]) {
      order = pos === -1 ? [i] : [];
    } else if (kind === "pick-many" || kind === "rank") {
      if (pos === -1) {
        order.push(i);
      } else {
        order.splice(pos, 1);
      }
    }
    renderSelection();
    syncToggleFrame();
  }

  if (beforeReview) {
    beforeButtons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        setBeforeView(btn.dataset.beforeView);
      });
    });
    setBeforeView(section.dataset.beforeDefaultView || beforeReview.dataset.mode);
  }

  if (status !== "open") return; // decided requests are read-only

  if (pickOneKinds[kind] || kind === "pick-many" || kind === "rank") {
    variants.forEach(function (el) {
      el.addEventListener("click", function () {
        toggleVariant(el);
      });
      if (beforeReview) {
        el.addEventListener("keydown", function (event) {
          if (event.key !== " " && event.code !== "Space") return;
          event.preventDefault();
          toggleVariant(el);
        });
      }
    });
  }

  function submit(selected) {
    var payload = {
      selected: selected,
      comment: commentBox ? commentBox.value.trim() || null : null,
    };
    fetch("/r/" + reqId + "/decide" + window.location.search, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(payload),
    })
      .then(function (resp) {
        if (!resp.ok) {
          return resp.json().then(function (err) {
            throw new Error(err.detail || "failed to submit decision");
          });
        }
        return resp.json();
      })
      .then(function () {
        window.location.reload();
      })
      .catch(function (err) {
        alert(err.message);
      });
  }

  if (kind === "approve") {
    section.querySelectorAll("[data-approve]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        submit(btn.dataset.approve === "yes" ? [1] : []);
      });
    });
  } else if (decideBtn) {
    decideBtn.addEventListener("click", function () {
      if (pickOneKinds[kind] && order.length === 0) {
        alert("Pick a variant first.");
        return;
      }
      submit(kind === "comment" ? [] : order);
    });
  }
})();
