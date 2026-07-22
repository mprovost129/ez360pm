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
