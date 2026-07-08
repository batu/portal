// Gallery web UI — vanilla JS, no build step, no dependencies.
(function () {
  var section = document.querySelector(".request-detail");
  if (!section) return; // not a request detail page

  var reqId = section.dataset.reqId;
  var kind = section.dataset.kind;
  var status = section.dataset.status;
  if (status !== "open") return; // decided requests are read-only

  var variants = Array.prototype.slice.call(section.querySelectorAll(".variant"));
  var commentBox = section.querySelector(".comment-box");
  var decideBtn = document.getElementById("decide-btn");

  // order[] holds selected variant indices in the order they were tapped.
  // For pick-one/approve this is at most one element; for rank, order matters.
  var order = [];
  var pickOneKinds = { "pick-one": true, "before-after": true };

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
        badge.hidden = true;
      } else {
        el.classList.add("selected");
        if (kind === "rank") {
          badge.hidden = false;
          badge.textContent = String(pos + 1);
        } else {
          badge.hidden = true;
        }
      }
    });
  }

  function toggleVariant(el) {
    var i = idxOf(el);
    var pos = order.indexOf(i);
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
  }

  if (pickOneKinds[kind] || kind === "pick-many" || kind === "rank") {
    variants.forEach(function (el) {
      el.addEventListener("click", function () {
        toggleVariant(el);
      });
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
