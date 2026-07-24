function formatElapsed(totalSeconds) {
    const seconds = Math.max(0, Math.floor(totalSeconds));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainingSeconds = seconds % 60;
    return [hours, minutes, remainingSeconds]
        .map((value) => String(value).padStart(2, "0"))
        .join(":");
}

const runningTimerStates = new WeakMap();

function monotonicNow() {
    if (window.performance && typeof window.performance.now === "function") {
        return window.performance.now();
    }
    return Date.now();
}

function initializeRunningTimers() {
    document.querySelectorAll("[data-running-timer]").forEach((timer) => {
        if (timer.dataset.timerPaused === "true") return;
        const startedAt = Number(timer.dataset.timerStartMs);
        const serverNow = Number(timer.dataset.timerServerNowMs);
        if (!Number.isFinite(startedAt) || !Number.isFinite(serverNow)) return;
        runningTimerStates.set(timer, {
            elapsedAtInitialization: Math.max(0, serverNow - startedAt),
            initializedAt: monotonicNow(),
        });
    });
}

function updateRunningTimers() {
    document.querySelectorAll("[data-running-timer]").forEach((timer) => {
        if (timer.dataset.timerPaused === "true") return;
        const state = runningTimerStates.get(timer);
        const clock = timer.querySelector("[data-timer-clock]");
        if (!state || !clock) return;
        const elapsedMilliseconds =
            state.elapsedAtInitialization +
            Math.max(0, monotonicNow() - state.initializedAt);
        clock.textContent = formatElapsed(
            elapsedMilliseconds / 1000,
        );
    });
}

initializeRunningTimers();
updateRunningTimers();
window.setInterval(updateRunningTimers, 1000);

function initializeProjectBillingFields() {
    const billingType = document.querySelector("#id_billing_type");
    const hourlyRate = document.querySelector("#id_hourly_rate");
    const fixedFee = document.querySelector("#id_fixed_fee");
    if (!billingType || !hourlyRate || !fixedFee) return;

    billingType.addEventListener("change", () => {
        if (billingType.value === "flat_fee") {
            hourlyRate.value = "";
        } else if (billingType.value === "hourly") {
            fixedFee.value = "";
        }
    });

    fixedFee.addEventListener("input", () => {
        if (fixedFee.value.trim() === "") return;
        billingType.value = "flat_fee";
        hourlyRate.value = "";
    });

    hourlyRate.addEventListener("input", () => {
        if (hourlyRate.value.trim() === "") return;
        billingType.value = "hourly";
        fixedFee.value = "";
    });
}

initializeProjectBillingFields();

function initializeProtectedForms() {
    document.addEventListener("submit", (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) return;

        if (form.dataset.submitting === "true") {
            event.preventDefault();
            return;
        }

        const confirmation = form.dataset.confirm;
        if (confirmation && !window.confirm(confirmation)) {
            event.preventDefault();
            return;
        }

        form.dataset.submitting = "true";
        form.setAttribute("aria-busy", "true");
        window.setTimeout(() => {
            form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach(
                (control) => {
                    control.disabled = true;
                    control.setAttribute("aria-disabled", "true");
                },
            );
        }, 0);
    });
}

initializeProtectedForms();

function focusFirstFormError() {
    const errorSummary = document.querySelector(".form-error-summary");
    const invalidField = document.querySelector(
        ".form-field--error input, .form-field--error select, .form-field--error textarea",
    );
    if (invalidField) {
        invalidField.focus();
    } else if (errorSummary) {
        errorSummary.focus();
    }
}

focusFirstFormError();

function initializeLineItemPreviews() {
    document.querySelectorAll("[data-line-item-form]").forEach((form) => {
        const rate = form.querySelector('[name="rate"]');
        const quantity = form.querySelector('[name="quantity"]');
        const taxRate = form.querySelector('[name="tax_rate"]');
        const subtotalOutput = form.querySelector("[data-line-subtotal]");
        const totalOutput = form.querySelector("[data-line-total]");
        if (!rate || !quantity || !taxRate || !subtotalOutput || !totalOutput) return;

        const update = () => {
            const subtotal = Math.max(0, Number(rate.value) || 0) *
                Math.max(0, Number(quantity.value) || 0);
            const tax = subtotal * Math.max(0, Number(taxRate.value) || 0) / 100;
            subtotalOutput.textContent = `$${subtotal.toFixed(2)}`;
            totalOutput.textContent = `$${(subtotal + tax).toFixed(2)}`;
        };
        [rate, quantity, taxRate].forEach((field) => {
            field.addEventListener("input", update);
        });
        update();
    });
}

function initializeTimeSelection() {
    document.querySelectorAll("[data-select-all-time]").forEach((button) => {
        const form = button.closest("form");
        const choices = form?.querySelectorAll('[data-time-entry-choices] input[type="checkbox"]');
        const grouping = form?.querySelector('[name="grouping"]');
        const preview = form?.querySelector("[data-time-grouping-preview]");
        if (!choices?.length) return;

        const updatePreview = () => {
            const selected = Array.from(choices).filter((choice) => choice.checked);
            if (!selected.length) {
                preview.textContent = "Select time entries to preview the invoice lines.";
                return;
            }
            const hours = selected.reduce(
                (total, choice) => total + (Number(choice.dataset.hours) || 0),
                0,
            );
            const amount = selected.reduce(
                (total, choice) => total + (Number(choice.dataset.amount) || 0),
                0,
            );
            let lineCount = 1;
            if (grouping.value === "individual") {
                lineCount = selected.length;
            } else if (grouping.value === "description") {
                lineCount = new Set(selected.map((choice) => choice.dataset.description)).size;
            }
            preview.textContent = `${selected.length} selected · ${hours.toFixed(2)} hours · $${amount.toFixed(2)} · ${lineCount} invoice line${lineCount === 1 ? "" : "s"}`;
        };

        button.addEventListener("click", () => {
            const shouldSelect = Array.from(choices).some((choice) => !choice.checked);
            choices.forEach((choice) => {
                choice.checked = shouldSelect;
            });
            button.textContent = shouldSelect ? "Clear all" : "Select all";
            updatePreview();
        });
        choices.forEach((choice) => choice.addEventListener("change", updatePreview));
        grouping?.addEventListener("change", updatePreview);
        updatePreview();
    });
}

function initializeRetainerPreview() {
    const mode = document.querySelector("#id_mode");
    const value = document.querySelector("#id_value[data-proposal-total]");
    if (!mode || !value) return;
    const preview = document.createElement("div");
    preview.className = "calculation-preview";
    preview.setAttribute("aria-live", "polite");
    value.closest(".form-field")?.append(preview);

    const update = () => {
        const entered = Math.max(0, Number(value.value) || 0);
        const proposalTotal = Math.max(0, Number(value.dataset.proposalTotal) || 0);
        const amount = mode.value === "percentage"
            ? proposalTotal * entered / 100
            : entered;
        preview.textContent = `Retainer invoice amount: $${amount.toFixed(2)}`;
    };
    mode.addEventListener("change", update);
    value.addEventListener("input", update);
    update();
}

function initializeMaximumRetainerCredit() {
    document.querySelectorAll("[data-retainer-credit-form]").forEach((form) => {
        const source = form.querySelector('[name="source_invoice"]');
        const amount = form.querySelector('[name="amount"]');
        const apply = form.querySelector("[data-apply-max-credit]");
        if (!source || !amount || !apply) return;
        apply.addEventListener("click", () => {
            const available = Number(source.selectedOptions[0]?.dataset.available) || 0;
            const remaining = Number(amount.dataset.remainingCharges) || 0;
            amount.value = Math.min(available, remaining).toFixed(2);
            amount.focus();
        });
    });
}

initializeLineItemPreviews();
initializeTimeSelection();
initializeRetainerPreview();
initializeMaximumRetainerCredit();

function initializeClientTabs() {
    const tabList = document.querySelector("[data-client-tabs]");
    const Tab = window.bootstrap?.Tab;
    if (!tabList || !Tab) return;

    const triggers = Array.from(
        tabList.querySelectorAll('[data-bs-toggle="tab"][data-bs-target^="#tab-"]'),
    );
    if (!triggers.length) return;

    const showHashTab = () => {
        const trigger = triggers.find(
            (candidate) => candidate.getAttribute("data-bs-target") === window.location.hash,
        );
        if (trigger) Tab.getOrCreateInstance(trigger).show();
    };

    triggers.forEach((trigger) => {
        trigger.addEventListener("shown.bs.tab", () => {
            const target = trigger.getAttribute("data-bs-target");
            if (!target || window.location.hash === target) return;
            window.history.replaceState(
                null,
                "",
                `${window.location.pathname}${window.location.search}${target}`,
            );
        });
    });

    window.addEventListener("hashchange", showHashTab);
    showHashTab();
}

initializeClientTabs();
