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

function initializeRunningTimers() {
    document.querySelectorAll("[data-running-timer]").forEach((timer) => {
        const startedAt = Number(timer.dataset.timerStartMs);
        const serverNow = Number(timer.dataset.timerServerNowMs);
        if (!Number.isFinite(startedAt) || !Number.isFinite(serverNow)) return;
        runningTimerStates.set(timer, {
            startedAt,
            clockOffset: serverNow - Date.now(),
        });
    });
}

function updateRunningTimers() {
    document.querySelectorAll("[data-running-timer]").forEach((timer) => {
        const state = runningTimerStates.get(timer);
        const clock = timer.querySelector("[data-timer-clock]");
        if (!state || !clock) return;
        const serverAdjustedNow = Date.now() + state.clockOffset;
        clock.textContent = formatElapsed(
            (serverAdjustedNow - state.startedAt) / 1000,
        );
    });
}

initializeRunningTimers();
updateRunningTimers();
window.setInterval(updateRunningTimers, 1000);
