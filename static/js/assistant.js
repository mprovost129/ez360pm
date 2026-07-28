(() => {
    const form = document.querySelector("[data-assistant-form]");
    const transcript = document.querySelector("[data-assistant-transcript]");
    const input = document.querySelector("[data-assistant-input]");
    const submit = document.querySelector("[data-assistant-submit]");
    const drawer = document.getElementById("assistantDrawer");
    const insightsContainer = document.querySelector("[data-assistant-insights]");
    const suggestionsContainer = document.querySelector("[data-assistant-suggestions]");
    const newConversation = document.querySelector("[data-assistant-new-conversation]");
    const actionCenterLink = document.querySelector("[data-assistant-action-center-link]");
    if (!form || !transcript || !input || !submit || !drawer) return;

    const csrfToken = form.querySelector('[name="csrfmiddlewaretoken"]')?.value || "";
    const initialTranscript = transcript.innerHTML;
    const conversationStorageKey = "ez360pm:assistant:conversation";
    function newConversationId() {
        if (window.crypto?.randomUUID) return window.crypto.randomUUID();
        return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (character) => {
            const random = Math.floor(Math.random() * 16);
            const value = character === "x" ? random : ((random & 0x3) | 0x8);
            return value.toString(16);
        });
    }
    function loadConversationId() {
        try {
            const stored = window.sessionStorage.getItem(conversationStorageKey);
            if (stored) return stored;
            const created = newConversationId();
            window.sessionStorage.setItem(conversationStorageKey, created);
            return created;
        } catch {
            return newConversationId();
        }
    }
    function saveConversationId(value) {
        conversationId = value || newConversationId();
        try { window.sessionStorage.setItem(conversationStorageKey, conversationId); } catch {}
    }
    let conversationId = loadConversationId();
    let homeLoadedAt = 0;
    let homeRefreshSeconds = 3600;

    function scrollTranscript() {
        transcript.scrollTop = transcript.scrollHeight;
    }

    function appendMessage(kind, text, links = [], interactionId = null) {
        const wrapper = document.createElement("div");
        wrapper.className = `assistant-message assistant-message--${kind}`;
        const paragraph = document.createElement("p");
        paragraph.className = "mb-0";
        paragraph.textContent = text;
        wrapper.append(paragraph);
        if (links.length) {
            const linkList = document.createElement("div");
            linkList.className = "assistant-links";
            links.forEach((item) => {
                if (!item?.url || !item?.label) return;
                const link = document.createElement("a");
                link.href = item.url;
                link.textContent = item.label;
                link.className = "assistant-link";
                linkList.append(link);
            });
            wrapper.append(linkList);
        }
        if (kind === "assistant" && interactionId) {
            const feedback = document.createElement("div");
            feedback.className = "assistant-feedback mt-2 d-flex flex-wrap gap-2 align-items-center";
            const label = document.createElement("span");
            label.className = "small text-secondary";
            label.textContent = "Was this useful?";
            const helpful = document.createElement("button");
            helpful.type = "button";
            helpful.className = "btn btn-sm btn-link p-0";
            helpful.textContent = "Helpful";
            const notHelpful = document.createElement("button");
            notHelpful.type = "button";
            notHelpful.className = "btn btn-sm btn-link p-0";
            notHelpful.textContent = "Not helpful";
            const report = document.createElement("button");
            report.type = "button";
            report.className = "btn btn-sm btn-link text-danger p-0";
            report.textContent = "Report issue";

            async function submitRating(rating) {
                helpful.disabled = true;
                notHelpful.disabled = true;
                try {
                    let comment = "";
                    if (rating === "not_helpful") {
                        comment = window.prompt("What was wrong or missing? You can leave this blank.", "") || "";
                    }
                    await postJson(drawer.dataset.assistantFeedbackUrl, {
                        interaction_id: interactionId,
                        rating,
                        category: "answer",
                        comment,
                    });
                    feedback.replaceChildren();
                    const thanks = document.createElement("span");
                    thanks.className = "small text-secondary";
                    thanks.textContent = "Feedback recorded.";
                    feedback.append(thanks);
                } catch (error) {
                    helpful.disabled = false;
                    notHelpful.disabled = false;
                    appendMessage("error", error.message);
                }
            }

            helpful.addEventListener("click", () => submitRating("helpful"));
            notHelpful.addEventListener("click", () => submitRating("not_helpful"));
            report.addEventListener("click", async () => {
                const summary = window.prompt("Briefly describe the AI issue.", "") || "";
                if (!summary.trim()) return;
                const pauseImmediately = window.confirm(
                    "Is this a critical safety, privacy, or financial issue that should pause AI for your company immediately?"
                );
                try {
                    const data = await postJson(drawer.dataset.assistantIncidentUrl, {
                        interaction_id: interactionId,
                        severity: pauseImmediately ? "critical" : "medium",
                        category: "other",
                        summary: summary.trim(),
                    });
                    report.disabled = true;
                    report.textContent = data.assistant_suspended
                        ? "Issue reported — AI paused"
                        : "Issue reported";
                } catch (error) {
                    appendMessage("error", error.message);
                }
            });
            feedback.append(label, helpful, notHelpful, report);
            wrapper.append(feedback);
        }
        transcript.append(wrapper);
        scrollTranscript();
        return wrapper;
    }

    function appendPendingAction(action) {
        if (!action?.token || transcript.querySelector(`[data-action-token="${CSS.escape(action.token)}"]`)) return;
        const preview = action.preview || {};
        const card = document.createElement("div");
        card.className = "assistant-action-card";
        card.dataset.actionToken = action.token;
        const externalCommit = action.risk_level === "external_commit";
        if (externalCommit) card.classList.add("assistant-action-card--external");

        const title = document.createElement("h3");
        title.className = "h6 mb-1";
        title.textContent = preview.title || "Confirm action";
        card.append(title);

        const summary = document.createElement("p");
        summary.className = "mb-2";
        summary.textContent = preview.summary || "Review this action before continuing.";
        card.append(summary);

        if (Array.isArray(preview.details) && preview.details.length) {
            const details = document.createElement("ul");
            details.className = "small mb-3 ps-3";
            preview.details.forEach((detail) => {
                const item = document.createElement("li");
                item.textContent = detail;
                details.append(item);
            });
            card.append(details);
        }

        let reviewCheckbox = null;
        if (externalCommit) {
            const review = document.createElement("label");
            review.className = "assistant-final-review form-check mb-3";
            reviewCheckbox = document.createElement("input");
            reviewCheckbox.type = "checkbox";
            reviewCheckbox.className = "form-check-input";
            reviewCheckbox.dataset.assistantFinalReview = action.token;
            const reviewText = document.createElement("span");
            reviewText.className = "form-check-label";
            reviewText.textContent = "I reviewed the recipient, amounts, dates, and resulting action.";
            review.append(reviewCheckbox, reviewText);
            card.append(review);
        }

        const actions = document.createElement("div");
        actions.className = "d-flex gap-2";
        const confirm = document.createElement("button");
        confirm.type = "button";
        confirm.className = "btn btn-sm btn-primary";
        confirm.textContent = preview.confirm_label || "Confirm";
        confirm.dataset.assistantConfirm = action.token;
        if (externalCommit) confirm.dataset.assistantExternalCommit = "1";
        confirm.disabled = externalCommit;
        if (reviewCheckbox) {
            reviewCheckbox.addEventListener("change", () => {
                confirm.disabled = !reviewCheckbox.checked;
            });
        }
        const revise = document.createElement("button");
        revise.type = "button";
        revise.className = "btn btn-sm btn-outline-primary";
        revise.textContent = "Revise";
        revise.dataset.assistantRevise = action.token;
        revise.dataset.assistantRevisionPrompt = [
            `Revise this prepared action: ${preview.title || "action"}.`,
            preview.summary || "",
            ...(Array.isArray(preview.details) ? preview.details : []),
            "Requested changes:",
        ].filter(Boolean).join(" ");
        const cancel = document.createElement("button");
        cancel.type = "button";
        cancel.className = "btn btn-sm btn-outline-secondary";
        cancel.textContent = "Cancel";
        cancel.dataset.assistantCancel = action.token;
        actions.append(confirm, revise, cancel);
        card.append(actions);
        transcript.append(card);
        scrollTranscript();
    }

    async function postJson(url, body = {}) {
        const response = await fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": csrfToken,
                "X-Requested-With": "XMLHttpRequest",
            },
            body: JSON.stringify(body),
            credentials: "same-origin",
        });
        let data;
        try {
            data = await response.json();
        } catch {
            data = { ok: false, error: "EZ360PM returned an unreadable response." };
        }
        if (!response.ok || !data.ok) {
            throw new Error(data.error || "The assistant request failed.");
        }
        return data;
    }

    function recordSuggestion(suggestionId) {
        if (!suggestionId || !drawer.dataset.assistantEventUrl) return;
        postJson(drawer.dataset.assistantEventUrl, {
            event_type: "suggestion_used",
            suggestion_id: suggestionId,
        }).catch(() => {});
    }

    function bindSuggestion(button) {
        button.addEventListener("click", () => {
            const prompt = button.dataset.assistantSuggestion;
            if (!prompt) return;
            recordSuggestion(button.dataset.assistantSuggestionId || "");
            ask(prompt);
        });
    }

    function renderSuggestions(suggestions) {
        if (!suggestionsContainer || !Array.isArray(suggestions) || !suggestions.length) return;
        suggestionsContainer.replaceChildren();
        suggestions.forEach((suggestion) => {
            const button = document.createElement("button");
            button.className = "assistant-suggestion";
            button.type = "button";
            button.textContent = suggestion.label;
            button.dataset.assistantSuggestion = suggestion.prompt;
            button.dataset.assistantSuggestionId = suggestion.id;
            bindSuggestion(button);
            suggestionsContainer.append(button);
        });
    }

    function renderInsights(insights) {
        if (!insightsContainer) return;
        insightsContainer.replaceChildren();
        if (!Array.isArray(insights) || !insights.length) {
            insightsContainer.classList.add("d-none");
            return;
        }
        const heading = document.createElement("div");
        heading.className = "assistant-insights-heading";
        heading.textContent = "Workflow alerts";
        insightsContainer.append(heading);
        insights.forEach((insight) => {
            const card = document.createElement("div");
            card.className = "assistant-insight";
            card.dataset.insightKey = insight.key;
            const body = document.createElement("div");
            const title = document.createElement("strong");
            title.textContent = insight.title;
            const summary = document.createElement("div");
            summary.className = "small text-secondary";
            summary.textContent = insight.summary;
            body.append(title, summary);
            const actions = document.createElement("div");
            actions.className = "assistant-insight-actions";
            if (insight.url) {
                const open = document.createElement("a");
                open.href = insight.url;
                open.className = "btn btn-sm btn-outline-primary";
                open.textContent = "Open";
                actions.append(open);
            }
            const dismiss = document.createElement("button");
            dismiss.type = "button";
            dismiss.className = "btn btn-sm btn-link text-secondary";
            dismiss.textContent = "Dismiss";
            dismiss.addEventListener("click", async () => {
                dismiss.disabled = true;
                try {
                    await postJson(drawer.dataset.assistantDismissUrl, { insight_key: insight.key });
                    card.remove();
                    if (!insightsContainer.querySelector(".assistant-insight")) {
                        insightsContainer.classList.add("d-none");
                    }
                } catch (error) {
                    dismiss.disabled = false;
                    appendMessage("error", error.message);
                }
            });
            actions.append(dismiss);
            card.append(body, actions);
            insightsContainer.append(card);
        });
        insightsContainer.classList.remove("d-none");
    }

    async function loadAssistantHome() {
        if (!drawer.dataset.assistantHomeUrl) return;
        if (homeLoadedAt && Date.now() - homeLoadedAt < homeRefreshSeconds * 1000) return;
        try {
            const response = await fetch(drawer.dataset.assistantHomeUrl, {
                headers: { "X-Requested-With": "XMLHttpRequest" },
                credentials: "same-origin",
            });
            const data = await response.json();
            if (!response.ok || !data.ok) return;
            renderInsights(data.insights || []);
            renderSuggestions(data.suggestions || []);
            (data.pending_actions || []).forEach(appendPendingAction);
            if (actionCenterLink) {
                const pendingCount = (data.pending_actions || []).length;
                actionCenterLink.textContent = pendingCount
                    ? `Action center (${pendingCount})`
                    : "Action center";
            }
            homeLoadedAt = Date.now();
            homeRefreshSeconds = Math.max(Number(data.refresh_seconds) || 3600, 60);
        } catch {
            // The assistant remains usable when local insight loading fails.
        }
    }

    async function ask(prompt) {
        appendMessage("user", prompt);
        const waiting = appendMessage("assistant", "Working…");
        submit.disabled = true;
        input.disabled = true;
        try {
            const data = await postJson(form.dataset.askUrl, {
                prompt,
                conversation_id: conversationId,
                page_path: window.location.pathname,
            });
            if (data.conversation_id) saveConversationId(data.conversation_id);
            waiting.remove();
            appendMessage("assistant", data.message, data.links || [], data.interaction_id || null);
            (data.pending_actions || []).forEach(appendPendingAction);
        } catch (error) {
            waiting.remove();
            appendMessage("error", error.message);
        } finally {
            submit.disabled = false;
            input.disabled = false;
            input.focus();
        }
    }

    form.addEventListener("submit", (event) => {
        event.preventDefault();
        const prompt = input.value.trim();
        if (!prompt) return;
        input.value = "";
        ask(prompt);
    });

    document.querySelectorAll("[data-assistant-suggestion]").forEach(bindSuggestion);
    newConversation?.addEventListener("click", () => {
        saveConversationId(newConversationId());
        transcript.innerHTML = initialTranscript;
        transcript.querySelectorAll("[data-assistant-suggestion]").forEach(bindSuggestion);
        appendMessage("assistant", "Started a new conversation. Pending actions remain available in the Action center.");
        homeLoadedAt = 0;
        loadAssistantHome();
        input.value = "";
        input.focus();
    });
    drawer.addEventListener("show.bs.offcanvas", loadAssistantHome);

    transcript.addEventListener("click", async (event) => {
        const button = event.target.closest(
            "[data-assistant-confirm], [data-assistant-revise], [data-assistant-cancel]"
        );
        if (!button) return;
        const token = button.dataset.assistantConfirm
            || button.dataset.assistantRevise
            || button.dataset.assistantCancel;
        const mode = button.dataset.assistantConfirm ? "confirm" : "cancel";
        const isRevision = Boolean(button.dataset.assistantRevise);
        const card = button.closest("[data-action-token]");
        card?.querySelectorAll("button").forEach((control) => { control.disabled = true; });
        try {
            const data = await postJson(
                `/assistant/actions/${token}/${mode}/`,
                button.dataset.assistantExternalCommit
                    ? { final_review_acknowledged: true }
                    : (mode === "cancel" ? { reason: isRevision ? "revise" : "cancel" } : {})
            );
            card?.remove();
            if (isRevision) {
                input.value = button.dataset.assistantRevisionPrompt || "Revise this prepared action: ";
                input.focus();
                input.setSelectionRange(input.value.length, input.value.length);
                appendMessage("assistant", "The original action was canceled. Describe the changes, then send the revised request.");
                return;
            }
            appendMessage("assistant", data.message || "Action completed.", data.links || []);
            window.dispatchEvent(new CustomEvent("ez360pm:assistant-action-complete", { detail: data }));
            if (typeof data.redirect_url === "string" && data.redirect_url.startsWith("/")) {
                window.setTimeout(() => window.location.assign(data.redirect_url), 500);
            } else if (data.refresh_page) {
                window.setTimeout(() => window.location.reload(), 500);
            }
        } catch (error) {
            card?.querySelectorAll("button").forEach((control) => { control.disabled = false; });
            appendMessage("error", error.message);
        }
    });
})();
