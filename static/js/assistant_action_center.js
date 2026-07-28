(() => {
    const center = document.querySelector("[data-ai-action-center]");
    if (!center) return;
    const csrfToken = document.querySelector('[name="csrfmiddlewaretoken"]')?.value
        || document.cookie.split("; ").find((item) => item.startsWith("csrftoken="))?.split("=")[1]
        || "";

    async function post(url, body = {}) {
        const response = await fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": decodeURIComponent(csrfToken),
                "X-Requested-With": "XMLHttpRequest",
            },
            credentials: "same-origin",
            body: JSON.stringify(body),
        });
        const data = await response.json().catch(() => ({ ok: false, error: "Unreadable server response." }));
        if (!response.ok || !data.ok) throw new Error(data.error || "The action failed.");
        return data;
    }

    center.querySelectorAll("[data-action-center-card]").forEach((card) => {
        const confirm = card.querySelector("[data-action-confirm-url]");
        const cancel = card.querySelector("[data-action-cancel-url]");
        const review = card.querySelector("[data-action-review]");
        const status = card.querySelector("[data-action-status]");
        if (review && confirm) {
            review.addEventListener("change", () => {
                confirm.disabled = !review.checked;
            });
        }

        async function execute(button, url, body) {
            button.disabled = true;
            if (status) {
                status.classList.remove("d-none", "text-danger");
                status.textContent = "Working…";
            }
            try {
                const data = await post(url, body);
                card.classList.add("opacity-75");
                card.querySelectorAll("button, input").forEach((control) => { control.disabled = true; });
                if (status) status.textContent = data.message || "Action completed.";
                window.dispatchEvent(new CustomEvent("ez360pm:assistant-action-complete", { detail: data }));
            } catch (error) {
                button.disabled = false;
                if (status) {
                    status.classList.add("text-danger");
                    status.textContent = error.message;
                }
            }
        }

        confirm?.addEventListener("click", () => execute(
            confirm,
            confirm.dataset.actionConfirmUrl,
            { final_review_acknowledged: Boolean(review?.checked) },
        ));
        cancel?.addEventListener("click", () => execute(
            cancel,
            cancel.dataset.actionCancelUrl,
            { reason: "cancel" },
        ));
    });
})();
