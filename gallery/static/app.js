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

  function decideErrorMessage(detail) {
    // P5b made the decide 409 detail a dict; render its human fields readably.
    // Plain-string details (every other 4xx on this path) pass through verbatim.
    if (typeof detail === "string") return detail || "failed to submit decision";
    if (detail && typeof detail === "object") {
      if (detail.error === "verdict_exists") {
        var n = detail.verdict_count;
        return "This request already has a decision (" + n +
          (n === 1 ? " verdict" : " verdicts") + "). Reload to see it.";
      }
      if (detail.error === "superseded") {
        return "This request was superseded" +
          (detail.successor ? " by " + detail.successor : "") + ". Reload to continue.";
      }
      if (detail.error === "closed") {
        return "This request is closed" +
          (detail.reason ? ": " + detail.reason : "") + ".";
      }
    }
    return "failed to submit decision";
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
            throw new Error(decideErrorMessage(err.detail));
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

// ── Variant grid extras: per-row control + lightbox viewer ──────────────
(function () {
  var section = document.querySelector(".request-detail");
  if (!section) return;
  var grid = section.querySelector(".variant-grid");
  if (!grid) return;

  // Per-row control (persisted). "auto" falls back to the server default.
  var COLS_KEY = "portal.variantCols";
  var control = document.createElement("div");
  control.className = "cols-control";
  control.appendChild(document.createTextNode("per row:"));
  ["3", "4", "5", "6", "auto"].forEach(function (opt) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = opt;
    btn.dataset.cols = opt;
    control.appendChild(btn);
  });
  grid.parentNode.insertBefore(control, grid);
  function applyCols(value) {
    if (value && value !== "auto") grid.style.setProperty("--variant-cols", value);
    else grid.style.removeProperty("--variant-cols");
    control.querySelectorAll("button").forEach(function (b) {
      b.classList.toggle("active", b.dataset.cols === (value || "auto"));
    });
  }
  applyCols(localStorage.getItem(COLS_KEY));
  control.addEventListener("click", function (e) {
    var btn = e.target.closest("button");
    if (!btn) return;
    localStorage.setItem(COLS_KEY, btn.dataset.cols);
    applyCols(btn.dataset.cols);
  });

  // Lightbox: click an image to view large; arrows / swipe keys navigate.
  // One reusable overlay; neighbor images are preloaded so navigation is
  // instant and nothing re-renders the page behind it.
  var items = [];
  section.querySelectorAll(".variant").forEach(function (el) {
    var img = el.querySelector(".variant-media img");
    if (!img) return;
    var link = el.querySelector(".variant-media a");
    var caption = el.querySelector(".variant-caption");
    items.push({
      url: link ? link.href : img.src,
      idx: el.dataset.idx,
      caption: caption ? caption.textContent : "",
      anchor: link || img,
    });
  });
  if (items.length === 0) return;

  var overlay = document.createElement("div");
  overlay.className = "lightbox";
  overlay.hidden = true;
  overlay.innerHTML =
    '<button type="button" class="lightbox-nav prev" aria-label="Previous">&#8249;</button>' +
    '<figure><img alt=""><figcaption></figcaption></figure>' +
    '<button type="button" class="lightbox-nav next" aria-label="Next">&#8250;</button>' +
    '<button type="button" class="lightbox-full" aria-label="Full screen" title="Full screen — phone-sized, like the real game">&#x26F6;</button>' +
    '<button type="button" class="lightbox-close" aria-label="Close">&times;</button>';
  document.body.appendChild(overlay);
  var lbImg = overlay.querySelector("img");
  var lbCaption = overlay.querySelector("figcaption");
  var current = 0;

  function preload(i) {
    if (i < 0 || i >= items.length) return;
    var im = new Image();
    im.src = items[i].url;
  }
  function show(i) {
    current = (i + items.length) % items.length;
    lbImg.src = items[current].url;
    lbCaption.textContent = items[current].caption || "#" + items[current].idx;
    overlay.hidden = false;
    document.body.style.overflow = "hidden";
    preload(current + 1);
    preload(current - 1);
  }
  function close() {
    if (document.fullscreenElement) document.exitFullscreen();
    overlay.classList.remove("fullpage");
    overlay.hidden = true;
    document.body.style.overflow = "";
  }

  // Full-page mode: true browser fullscreen with the media alone at phone
  // proportions on black — as close to holding the final game as the web gets.
  var fullBtn = overlay.querySelector(".lightbox-full");
  fullBtn.addEventListener("click", function () {
    if (overlay.classList.contains("fullpage")) {
      overlay.classList.remove("fullpage");
      if (document.fullscreenElement) document.exitFullscreen();
      return;
    }
    overlay.classList.add("fullpage");
    if (overlay.requestFullscreen) overlay.requestFullscreen().catch(function () {});
  });
  document.addEventListener("fullscreenchange", function () {
    if (!document.fullscreenElement) overlay.classList.remove("fullpage");
  });
  items.forEach(function (item, i) {
    item.anchor.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation(); // do not toggle selection when opening the viewer
      show(i);
    });
  });
  overlay.querySelector(".prev").addEventListener("click", function () { show(current - 1); });
  overlay.querySelector(".next").addEventListener("click", function () { show(current + 1); });
  overlay.querySelector(".lightbox-close").addEventListener("click", close);
  overlay.addEventListener("click", function (e) {
    if (e.target === overlay) close();
  });
  document.addEventListener("keydown", function (e) {
    if (overlay.hidden) return;
    if (e.key === "ArrowLeft") show(current - 1);
    else if (e.key === "ArrowRight") show(current + 1);
    else if (e.key === "Escape") close();
  });
})();

// ── Chain view: compare-with-previous toggle ─────────────────────────────
(function () {
  var toggle = document.querySelector("[data-compare-toggle]");
  var panel = document.getElementById("chain-compare");
  if (!toggle || !panel) return;
  toggle.addEventListener("click", function () {
    var open = panel.hidden;
    panel.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
  });
})();

// ── Chain tabs: keep the active version visible in the scrollable strip ──
(function () {
  var active = document.querySelector(".chain-tab.active");
  if (active && active.scrollIntoView) {
    active.scrollIntoView({ inline: "center", block: "nearest" });
  }
})();

// ── Game builds: one directly-linkable tab per immutable release ─────────
(function () {
  var tabs = Array.prototype.slice.call(document.querySelectorAll("[data-build-tab]"));
  var panels = Array.prototype.slice.call(document.querySelectorAll("[data-build-panel]"));
  if (!tabs.length || !panels.length) return;

  function select(version, updateHash) {
    var selected = tabs.find(function (tab) { return tab.dataset.buildTab === version; }) || tabs[0];
    tabs.forEach(function (tab) {
      var active = tab === selected;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    panels.forEach(function (panel) {
      var active = panel.dataset.buildPanel === selected.dataset.buildTab;
      panel.hidden = !active;
      panel.querySelectorAll("video").forEach(function (video) {
        if (active && !video.getAttribute("src")) {
          video.setAttribute("src", video.dataset.src);
          video.load();
        } else if (!active) {
          video.pause();
        }
      });
      // One focused playable device at a time: the inactive tab's game is
      // unloaded, not merely hidden, so it stops running.
      panel.querySelectorAll("[data-play-frame]").forEach(function (frame) {
        if (active && !frame.getAttribute("src")) {
          startPlayFrame(frame);
        } else if (!active && frame.getAttribute("src")) {
          frame.removeAttribute("src");
          resetPlayFrameState(frame);
        }
      });
    });
    if (updateHash) history.replaceState(null, "", "#build-" + selected.dataset.buildTab);
    selected.scrollIntoView({ inline: "center", block: "nearest" });
  }

  tabs.forEach(function (tab, index) {
    tab.addEventListener("click", function () { select(tab.dataset.buildTab, true); });
    tab.addEventListener("keydown", function (event) {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      var offset = event.key === "ArrowRight" ? 1 : -1;
      var next = tabs[(index + offset + tabs.length) % tabs.length];
      select(next.dataset.buildTab, true);
      next.focus();
    });
  });

  // ── Play surface: device presets drive the iframe's real CSS pixel box ──
  var PLAY_TIMEOUT_MS = 15000;
  var STORAGE_KEY = "portal.play-surface";

  function readPreference() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
    } catch (err) {
      return {};
    }
  }

  function writePreference(value) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
    } catch (err) {
      /* private mode: the preset still applies for this page view */
    }
  }

  function resetPlayFrameState(frame) {
    var surface = frame.closest("[data-play-surface]");
    if (!surface) return;
    if (frame.dataset.playTimer) {
      clearTimeout(Number(frame.dataset.playTimer));
      delete frame.dataset.playTimer;
    }
    surface.querySelector("[data-play-loading]").hidden = false;
    surface.querySelector("[data-play-error]").hidden = true;
  }

  function startPlayFrame(frame) {
    resetPlayFrameState(frame);
    frame.setAttribute("src", frame.dataset.src);
    frame.dataset.playTimer = String(setTimeout(function () {
      var surface = frame.closest("[data-play-surface]");
      if (!surface) return;
      surface.querySelector("[data-play-loading]").hidden = true;
      surface.querySelector("[data-play-error]").hidden = false;
    }, PLAY_TIMEOUT_MS));
  }

  var playSurfaces = [];

  function syncPlaySurfaces() {
    playSurfaces.forEach(function (apply) { apply(); });
  }

  function initPlaySurface(surface) {
    var presetOptions = Array.prototype.slice.call(surface.querySelectorAll("option[data-device-preset]"));
    var deviceSelects = Array.prototype.slice.call(surface.querySelectorAll("[data-device-select]"));
    var orientationToggle = surface.querySelector("[data-orientation-toggle]");
    var deviceFrame = surface.querySelector("[data-device-frame]");
    var deviceShell = surface.querySelector("[data-device-shell]");
    var fullscreenButton = surface.querySelector("[data-device-fullscreen]");
    var dims = surface.querySelector("[data-play-dims]");
    var deviceName = surface.querySelector("[data-play-device]");
    var frame = surface.querySelector("[data-play-frame]");
    var saved = readPreference();
    function findPreset(id) {
      return presetOptions.find(function (option) { return option.dataset.devicePreset === id; });
    }
    var selectedPreset = saved.preset && findPreset(saved.preset) ? saved.preset : "iphone-15-pro";
    var landscape = saved.landscape === true;

    function apply() {
      var preset = findPreset(selectedPreset);
      var presetWidth = Number(preset.dataset.deviceWidth);
      var presetHeight = Number(preset.dataset.deviceHeight);
      var width = landscape ? presetHeight : presetWidth;
      var height = landscape ? presetWidth : presetHeight;
      deviceFrame.style.setProperty("--device-w", width + "px");
      deviceFrame.style.setProperty("--device-h", height + "px");
      deviceSelects.forEach(function (select) {
        var matchingOption = Array.prototype.slice.call(select.options).find(function (option) {
          return option.dataset.devicePreset === selectedPreset;
        });
        select.value = matchingOption ? selectedPreset : "";
      });
      surface.querySelector("[data-safe-top]").style.height = (landscape ? 0 : Number(preset.dataset.safeTop)) + "px";
      surface.querySelector("[data-safe-bottom]").style.height = Number(preset.dataset.safeBottom) + "px";
      orientationToggle.querySelector("strong").textContent = landscape ? "Landscape" : "Portrait";
      orientationToggle.setAttribute("aria-pressed", String(landscape));
      deviceName.textContent = preset.dataset.deviceName;
      dims.textContent = width + " × " + height;
    }

    // Every surface on the page follows the one stored preference, so the
    // chosen device survives tab switches and reloads.
    function sync() {
      var pref = readPreference();
      if (pref.preset && findPreset(pref.preset)) selectedPreset = pref.preset;
      landscape = pref.landscape === true;
      apply();
    }
    playSurfaces.push(sync);

    deviceSelects.forEach(function (select) {
      select.addEventListener("change", function () {
        if (!select.value || select.value === selectedPreset) return;
        selectedPreset = select.value;
        writePreference({ preset: selectedPreset, landscape: landscape });
        syncPlaySurfaces();
      });
    });
    orientationToggle.addEventListener("click", function () {
      landscape = !landscape;
      writePreference({ preset: selectedPreset, landscape: landscape });
      syncPlaySurfaces();
    });
    fullscreenButton.addEventListener("click", function () {
      if (document.fullscreenElement) {
        document.exitFullscreen().then(syncFullscreenLabels);
      } else if (deviceShell.requestFullscreen) {
        deviceShell.requestFullscreen().then(syncFullscreenLabels);
      }
    });
    frame.addEventListener("load", function () {
      if (!frame.getAttribute("src")) return;
      if (frame.dataset.playTimer) {
        clearTimeout(Number(frame.dataset.playTimer));
        delete frame.dataset.playTimer;
      }
      surface.querySelector("[data-play-loading]").hidden = true;
      surface.querySelector("[data-play-error]").hidden = true;
    });
    apply();
  }

  function syncFullscreenLabels() {
    document.querySelectorAll("[data-device-fullscreen]").forEach(function (button) {
      var shell = button.closest("[data-play-surface]").querySelector("[data-device-shell]");
      button.querySelector("strong").textContent = document.fullscreenElement === shell ? "Exit fullscreen" : "Fullscreen";
    });
  }

  document.querySelectorAll("[data-play-surface]").forEach(initPlaySurface);
  document.addEventListener("fullscreenchange", syncFullscreenLabels);

  var hashVersion = decodeURIComponent(window.location.hash.replace(/^#build-/, ""));
  select(hashVersion, false);
})();
