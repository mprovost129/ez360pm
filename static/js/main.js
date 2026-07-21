function formatElapsed(totalSeconds) {
    const seconds = Math.max(0, Math.floor(totalSeconds));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainingSeconds = seconds % 60;
    return [hours, minutes, remainingSeconds]
        .map((value) => String(value).padStart(2, "0"))
        .join(":");
}

function updateRunningTimers() {
    document.querySelectorAll("[data-running-timer]").forEach((timer) => {
        const startedAt = Date.parse(timer.dataset.timerStart);
        const clock = timer.querySelector("[data-timer-clock]");
        if (Number.isNaN(startedAt) || !clock) return;
        clock.textContent = formatElapsed((Date.now() - startedAt) / 1000);
    });
}

updateRunningTimers();
window.setInterval(updateRunningTimers, 1000);
