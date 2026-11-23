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
                <a class="bid-btn" href="/miniapp/auction/${Number(item.id)}">VIEW AUCTION</a>
            </div>
        </article>`;
    }).join("");

    if (!items.length) {
        messageBox.textContent = "There are no active auctions right now.";
    } else {
        messageBox.textContent = "";
    }
}

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
