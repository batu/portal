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
  var activeToggleIdx = null;

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

  function activeToggleCandidate() {
    if (activeToggleIdx !== null && order.indexOf(activeToggleIdx) !== -1) {
      return activeToggleIdx;
    }
    return order.length ? order[order.length - 1] : null;
  }

  function pauseVideos(root) {
    if (!root) return;
    Array.prototype.slice.call(root.querySelectorAll("video")).forEach(function (video) {
      video.pause();
    });
  }

  function clearBlink() {
    window.clearTimeout(blinkTimer);
    blinkTimer = null;
    if (toggleFrame) {
      toggleFrame.classList.remove("show-before");
    }
  }

  function syncActiveToggleIdx(preferred) {
    if (preferred !== null && order.indexOf(preferred) !== -1) {
      activeToggleIdx = preferred;
    } else {
      activeToggleIdx = order.length ? order[order.length - 1] : null;
    }
  }

  function syncToggleFrame() {
    if (!toggleFrame) return;
    var selected = activeToggleCandidate();
    toggleFrame.classList.toggle("has-candidate", selected !== null);
    if (selected === null) {
      clearBlink();
    }
    toggleCandidates.forEach(function (el) {
      var shouldHide = parseInt(el.dataset.toggleCandidate, 10) !== selected;
      if (shouldHide && !el.hidden) {
        pauseVideos(el);
      }
      el.hidden = shouldHide;
    });
  }

  function blinkToggleFrame() {
    if (!toggleFrame || !isToggleMode() || activeToggleCandidate() === null) return;
    clearBlink();
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
    if (sideBySideView && normalized !== "side-by-side") pauseVideos(sideBySideView);
    if (toggleView && normalized !== "toggle") pauseVideos(toggleView);
    if (normalized !== "toggle") clearBlink();
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
    if (isToggleMode() && pickOneKinds[kind] && pos !== -1) {
      syncActiveToggleIdx(i);
      blinkToggleFrame();
      return;
    }
    if (isToggleMode()) clearBlink();
    if (pickOneKinds[kind]) {
      order = pos === -1 ? [i] : [];
    } else if (kind === "pick-many" || kind === "rank") {
      if (pos === -1) {
        order.push(i);
      } else {
        order.splice(pos, 1);
      }
    }
    syncActiveToggleIdx(pos === -1 ? i : null);
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

  if (status !== "open" || section.dataset.canDecide === "false") return; // decided/archived requests are read-only

  if (pickOneKinds[kind] || kind === "pick-many" || kind === "rank") {
    variants.forEach(function (el) {
      el.addEventListener("click", function (event) {
        if (isToggleMode() && event.target.closest && event.target.closest("a")) {
          event.preventDefault();
        }
        toggleVariant(el);
      });
      if (beforeReview) {
        el.addEventListener("keydown", function (event) {
          if (event.key !== " " && event.code !== "Space") return;
          if (event.target !== el) return;
          event.preventDefault();
          if (isToggleMode() && order.indexOf(idxOf(el)) !== -1) {
            syncActiveToggleIdx(idxOf(el));
            blinkToggleFrame();
            return;
          }
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

(function () {
  var section = document.querySelector(".stream-detail");
  if (!section) return; // not a stream detail page

  var slug = section.dataset.streamSlug;
  if (!slug) return;

  function endpoint(action) {
    return "/s/" + encodeURIComponent(slug) + "/" + action;
  }

  function statusFor(form) {
    return form.querySelector("[data-form-status]");
  }

  function setStatus(form, message, isError) {
    var status = statusFor(form);
    if (!status) return;
    status.textContent = message;
    status.classList.toggle("is-error", Boolean(isError));
  }

  function submitJson(form, action, payload) {
    var button = form.querySelector("button[type='submit']");
    if (button) button.disabled = true;
    setStatus(form, "Sending...", false);
    fetch(endpoint(action), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(payload),
    })
      .then(function (resp) {
        if (!resp.ok) {
          return resp.json().catch(function () {
            return {};
          }).then(function (err) {
            throw new Error(err.detail || "failed to send message");
          });
        }
        return resp.json();
      })
      .then(function () {
        window.location.reload();
      })
      .catch(function (err) {
        setStatus(form, err.message, true);
        if (button) button.disabled = false;
      });
  }

  function textPayload(form) {
    var textarea = form.querySelector("textarea[name='text']");
    var text = textarea ? textarea.value.trim() : "";
    if (!text) {
      setStatus(form, "Message is required.", true);
      return null;
    }
    return { text: text };
  }

  var noteForm = section.querySelector("[data-stream-note-form]");
  if (noteForm) {
    noteForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var payload = textPayload(noteForm);
      if (!payload) return;
      submitJson(noteForm, "note", payload);
    });
  }

  Array.prototype.slice.call(section.querySelectorAll("[data-answer-form]")).forEach(function (form) {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var payload = textPayload(form);
      if (!payload) return;
      var questionId = form.querySelector("input[name='question_id']");
      payload.question_id = questionId ? questionId.value : "";
      submitJson(form, "answer", payload);
    });
  });
})();
