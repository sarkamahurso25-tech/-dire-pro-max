const auctionGrid = document.getElementById("auctions");
const messageBox = document.getElementById("message");
const countBox = document.getElementById("auction-count");

function escapeHTML(value) {
    return String(value ?? "").replace(/[&<>"']/g, char => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;",
        '"': "&quot;", "'": "&#039;"
    })[char]);
}

function formatTime(seconds) {
    seconds = Math.max(0, Number(seconds) || 0);
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    return `${days}d ${hours}h ${minutes}m ${secs}s`;
}

function renderAuctions(items) {
    auctionGrid.innerHTML = items.map(item => {
        const image = item.image_url
            ? `<img src="${escapeHTML(item.image_url)}" alt="${escapeHTML(item.title)}" loading="lazy">`
            : `<div class="image-placeholder">DIRE PRO MAX</div>`;

        return `
        <article class="auction-card">
            ${image}
            <div class="card-body">
                <h3>${escapeHTML(item.title)}</h3>
                <div class="code">Auction Code: ${escapeHTML(item.code)}</div>
                <div class="fee">Service Fee: ${escapeHTML(item.service_fee)} Br</div>
                <div class="timer">
                    ⏱ <span class="countdown" data-seconds="${Number(item.remaining_seconds)}">
                    ${formatTime(item.remaining_seconds)}</span>
                </div>
                <div class="code">${Number(item.bids_count)} bids submitted</div>

                <div class="bid-stepper" data-minimum="${Number(item.minimum_bid) || 10}">
                    <label>YOUR BID AMOUNT</label>
                    <div class="bid-stepper-controls">
                        <button type="button" class="bid-step-btn"
                                data-step="-1" aria-label="Decrease bid">−</button>
                        <span class="bid-step-value">${Number(item.minimum_bid) || 10} Br</span>
                        <button type="button" class="bid-step-btn"
                                data-step="1" aria-label="Increase bid">+</button>
                    </div>
                </div>

                <a class="bid-btn"
                   data-auction-id="${Number(item.id)}"
                   href="/miniapp/auction/${Number(item.id)}?amount=${Number(item.minimum_bid) || 10}">
                   VIEW AUCTION
                </a>
            </div>
        </article>`;
    }).join("");

    if (!items.length) {
        messageBox.textContent = "There are no active auctions right now.";
    } else {
        messageBox.textContent = "";
    }
}

// Independent bid amount controls on each auction card.
auctionGrid.addEventListener("click", event => {
    const stepButton = event.target.closest(".bid-step-btn");
    if (!stepButton) return;

    const stepper = stepButton.closest(".bid-stepper");
    if (!stepper) return;

    const minimum = Math.max(0.01, Number(stepper.dataset.minimum) || 10);
    const valueBox = stepper.querySelector(".bid-step-value");
    const current = Number.parseFloat(valueBox.textContent) || minimum;
    const next = Math.max(minimum, current + (Number(stepButton.dataset.step) * 10));

    valueBox.textContent = `${next.toFixed(2).replace(/\\.00$/, "")} Br`;
});

auctionGrid.addEventListener("click", event => {
    const link = event.target.closest(".bid-btn");
    if (!link) return;

    const card = link.closest(".auction-card");
    const valueBox = card?.querySelector(".bid-step-value");
    const amount = Number.parseFloat(valueBox?.textContent) || 10;
    const auctionId = Number(link.dataset.auctionId);

    if (!Number.isInteger(auctionId) || auctionId < 1) return;

    event.preventDefault();
    window.location.href =
        `/miniapp/auction/${auctionId}?amount=${encodeURIComponent(amount)}`;
});

async function loadAuctions() {
    try {
        const response = await fetch("/api/miniapp/auctions");
        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(data.error || "Unable to load auctions.");
        }

        countBox.textContent = `${data.count} available`;
        renderAuctions(data.auctions);
    } catch (error) {
        messageBox.textContent = error.message;
        messageBox.classList.add("error");
        countBox.textContent = "Unavailable";
    }
}

setInterval(() => {
    document.querySelectorAll(".countdown").forEach(node => {
        let seconds = Number(node.dataset.seconds);
        seconds = Math.max(0, seconds - 1);
        node.dataset.seconds = seconds;
        node.textContent = formatTime(seconds);
    });
}, 1000);

loadAuctions();

// Refresh auction list periodically to remove expired auctions.
setInterval(loadAuctions, 30000);

// DIRE PRO MAX Welcome Screen
document.getElementById("start-bidding").addEventListener("click", () => {
    document.getElementById("welcome-screen").hidden = true;

    const marketplace = document.getElementById("marketplace");
    marketplace.hidden = false;

    marketplace.scrollIntoView({
        behavior: "smooth",
        block: "start"
    });
});
